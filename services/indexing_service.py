import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from weaviate.exceptions import WeaviateBaseError

from core.database import AsyncSessionLocal, auto_commit
from entity.dataset_entity import DocumentStatus, SegmentStatus, DEFAULT_PROCESS_RULE
from utils.lock import LOCK_DOCUMENT, LOCK_DATASET, distributed_lock
from models import Document, ProcessRule, Segment, UploadFile
from services.embedding_service import EmbeddingService
from services.file_service import FileExtractor
from services.jieba_service import JiebaService
from services.keyword_table_service import KeywordTableService
from services.process_rule_service import ProcessRuleService
from services.vector_service import VectorService
from utils.security import generate_text_hash
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

DOCUMENT_LOCK_EXPIRE = 300


async def build_document(document_id: str):
    """后台构建单个文档：解析、切片、索引、向量化。

    持有文档级锁，阻止并发的用户删除/修改操作。
    """

    db: AsyncSession = AsyncSessionLocal()

    try:
        document = await db.get(Document, document_id)
        if document is None:
            return
        dataset_id = str(document.dataset_id)

        async with distributed_lock(
            LOCK_DOCUMENT.format(document_id=document_id),
            timeout=5,
            expire=DOCUMENT_LOCK_EXPIRE,
        ):
            await _build_document_locked(db, document_id, dataset_id)

    except (SQLAlchemyError, WeaviateBaseError, ValueError, RuntimeError, OSError) as e:
        logger.exception("构建文档失败: %s", e)
        try:
            async with auto_commit(db):
                document = await db.get(Document, document_id)
                if document:
                    document.status = DocumentStatus.ERROR
                    document.error = str(e)[:500]
                    document.stopped_at = datetime.now()
        except SQLAlchemyError:
            logger.warning("更新文档错误状态失败 document_id=%s", document_id, exc_info=True)
    finally:
        await db.close()


async def _build_document_locked(db: AsyncSession, document_id: str, dataset_id: str):
    """在文档锁保护下执行索引流水线"""

    document = await db.get(Document, document_id)
    if document is None:
        return

    async with auto_commit(db):
        document.status = DocumentStatus.PARSING
        document.processing_started_at = datetime.now()

    # 1. 解析
    upload_file = await db.get(UploadFile, document.upload_file_id)
    text = await FileExtractor.extract(upload_file)

    process_rule = await db.get(ProcessRule, document.process_rule_id)
    if process_rule:
        text = ProcessRuleService.clean_text_by_process_rule(text, process_rule)
        splitter = ProcessRuleService.get_text_splitter_by_process_rule(
            process_rule, EmbeddingService.count_tokens
        )
    else:
        seg_cfg = DEFAULT_PROCESS_RULE["segment"]
        splitter = RecursiveCharacterTextSplitter(
            separators=seg_cfg["separators"],
            chunk_size=seg_cfg["chunk_size"],
            chunk_overlap=seg_cfg["chunk_overlap"],
            length_function=EmbeddingService.count_tokens,
        )

    async with auto_commit(db):
        document.character_count = len(text)
        document.status = DocumentStatus.SPLITTING
        document.parsing_completed_at = datetime.now()

    # 2. 切片
    chunks = await asyncio.to_thread(splitter.split_text, text)

    pos_result = await db.execute(
        select(Segment.position)
        .where(Segment.document_id == document.id)
        .order_by(Segment.position.desc())
        .limit(1)
    )
    position = pos_result.scalar() or 0

    node_ids, texts, metadatas = [], [], []
    total_tokens = 0
    for chunk in chunks:
        position += 1
        node_id = uuid.uuid4()
        token_count = EmbeddingService.count_tokens(chunk)
        total_tokens += token_count
        seg = Segment(
            account_id=document.account_id,
            dataset_id=document.dataset_id,
            document_id=document.id,
            node_id=node_id,
            position=position,
            content=chunk,
            character_count=len(chunk),
            token_count=token_count,
            keywords=JiebaService.extract_keywords(chunk),
            hash=generate_text_hash(chunk),
            status=SegmentStatus.INDEXING,
        )
        db.add(seg)
        await db.flush()
        node_ids.append(str(node_id))
        texts.append(chunk)
        metadatas.append({
            "account_id": str(document.account_id),
            "dataset_id": str(document.dataset_id),
            "document_id": str(document.id),
            "segment_id": str(seg.id),
            "document_enabled": False,
            "segment_enabled": False,
        })

    async with auto_commit(db):
        document.token_count = total_tokens
        document.status = DocumentStatus.INDEXING
        document.splitting_completed_at = datetime.now()

    # 3. 向量化 + 并行写 Weaviate
    vectors = await EmbeddingService.embed_documents(texts)
    await _write_vectors_parallel(node_ids, texts, vectors, metadatas)

    # 4. 标记完成
    new_segment_ids = []
    result = await db.execute(
        select(Segment).where(Segment.document_id == document.id)
    )
    for seg in result.scalars().all():
        seg.status = SegmentStatus.COMPLETE
        seg.enabled = True
        seg.indexing_completed_at = datetime.now()
        new_segment_ids.append(str(seg.id))

    async with auto_commit(db):
        document.status = DocumentStatus.COMPLETE
        document.enabled = True
        document.completed_at = datetime.now()
        document.indexing_completed_at = datetime.now()

    # 5. 写关键词倒排表（加数据集级锁，防止并发 read-modify-write 丢失更新）
    async with distributed_lock(
        LOCK_DATASET.format(dataset_id=dataset_id),
        timeout=10,
        expire=30,
    ):
        async with auto_commit(db):
            await KeywordTableService(db).add_keyword_table_from_ids(
                dataset_id, new_segment_ids
            )

    # 6. 同步 document_enabled / segment_enabled 到 Weaviate
    for nid in node_ids:
        try:
            await VectorService.update_node_properties(
                nid, {"document_enabled": True, "segment_enabled": True}
            )
        except WeaviateBaseError:
            logger.warning("同步向量库属性失败 node_id=%s", nid, exc_info=True)


async def _write_vectors_parallel(node_ids, texts, vectors, metadatas):
    """并行写入 Weaviate，单条失败不影响其他"""
    items = list(zip(node_ids, texts, vectors, metadatas))

    async def _write_one(nid, t, v, meta):
        try:
            await VectorService.add_segment(nid, t, v, meta)
        except WeaviateBaseError as e:
            logger.warning("写入向量库失败 node_id=%s: %s", nid, e)

    await asyncio.gather(*[_write_one(*item) for item in items])

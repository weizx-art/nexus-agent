import logging
import random
import time
from datetime import datetime
from typing import Sequence

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from weaviate.exceptions import WeaviateBaseError

from core.database import auto_commit
from entity.dataset_entity import DocumentStatus, ProcessType, DEFAULT_PROCESS_RULE
from utils.lock import LOCK_DOCUMENT, LOCK_DATASET, distributed_lock
from utils.exception import FailException, NotFoundException, ValidateErrorException
from models import Dataset, Document, ProcessRule, Segment, UploadFile
from schemas.common import PageData, make_paginator
from services.keyword_table_service import KeywordTableService
from services.vector_service import VectorService
from services.storage_service import ALLOWED_FILE

logger = logging.getLogger(__name__)


class DocumentService:
    """文档服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_owned(self, account_id, dataset_id, document_id) -> Document:
        doc = await self.db.get(Document, document_id)
        if (
            not doc
            or doc.account_id != account_id
            or str(doc.dataset_id) != str(dataset_id)
        ):
            raise NotFoundException("文档不存在")
        return doc

    async def create_documents(self, account_id, dataset_id, upload_file_ids: list[str],
                               process_type: str = ProcessType.AUTOMATIC, rule: dict | None = None):
        """建 ProcessRule + Document 记录，返回 document_id 列表（后台再做解析向量化）"""
        dataset = await self.db.get(Dataset, dataset_id)
        if not dataset or dataset.account_id != account_id:
            raise NotFoundException("该知识库不存在或无权限")

        upload_file_ids = list(dict.fromkeys(upload_file_ids))
        if not upload_file_ids or len(upload_file_ids) > 10:
            raise ValidateErrorException("文档数量须在 1-10 之间")

        result = await self.db.execute(
            select(UploadFile).where(
                UploadFile.account_id == account_id,
                UploadFile.id.in_(upload_file_ids),
            )
        )
        upload_files = result.scalars().all()
        valid = [u for u in upload_files if u.extension.lower() in ALLOWED_FILE]
        if not valid:
            raise FailException("暂未解析到合法文件，请重新上传")

        if process_type == ProcessType.AUTOMATIC:
            rule = DEFAULT_PROCESS_RULE.copy()
        else:
            if not rule or not isinstance(rule, dict):
                raise ValidateErrorException("自定义处理模式下，rule 不能为空")
            self._validate_rule(rule)

        batch = time.strftime("%Y%m%d%H%M%S") + str(random.randint(100000, 999999))
        async with auto_commit(self.db):
            process_rule = ProcessRule(
                account_id=account_id,
                dataset_id=dataset_id,
                mode=process_type,
                rule=rule,
            )
            self.db.add(process_rule)
            await self.db.flush()

            pos_result = await self.db.execute(
                select(func.coalesce(func.max(Document.position), 0)).where(Document.dataset_id == dataset_id)
            )
            last_pos = pos_result.scalar() or 0
            docs = []
            for uf in valid:
                last_pos += 1
                doc = Document(
                    account_id=account_id,
                    dataset_id=dataset_id,
                    upload_file_id=uf.id,
                    process_rule_id=process_rule.id,
                    batch=batch,
                    name=uf.name,
                    position=last_pos,
                    status=DocumentStatus.WAITING,
                )
                self.db.add(doc)
                docs.append(doc)
        return [str(d.id) for d in docs], batch

    @staticmethod
    def _validate_rule(rule: dict):
        seg = rule.get("segment")
        if not seg or not isinstance(seg, dict):
            raise ValidateErrorException("rule.segment 必须为字典")
        separators = seg.get("separators")
        if not isinstance(separators, list) or not separators:
            raise ValidateErrorException("rule.segment.separators 必须为非空列表")
        chunk_size = seg.get("chunk_size")
        if not isinstance(chunk_size, int) or not (100 <= chunk_size <= 1000):
            raise ValidateErrorException("rule.segment.chunk_size 必须在 100-1000 之间")
        chunk_overlap = seg.get("chunk_overlap")
        if not isinstance(chunk_overlap, int) or not (0 <= chunk_overlap <= chunk_size * 0.5):
            raise ValidateErrorException(f"rule.segment.chunk_overlap 必须在 0-{chunk_size * 0.5} 之间")

    async def list_documents(self, account_id, dataset_id, current_page, page_size, search_key="") -> PageData:
        q = select(Document).where(Document.account_id == account_id, Document.dataset_id == dataset_id)
        if search_key:
            q = q.where(Document.name.ilike(f"%{search_key}%"))
        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0
        rows_q = q.order_by(desc(Document.created_at)).offset((current_page - 1) * page_size).limit(page_size)
        rows = (await self.db.execute(rows_q)).scalars().all()
        return PageData(items=rows, paginator=make_paginator(total, current_page, page_size))

    async def get_document(self, account_id, dataset_id, document_id) -> Document:
        return await self._get_owned(account_id, dataset_id, document_id)

    async def update_name(self, account_id, dataset_id, document_id, name: str):
        doc = await self._get_owned(account_id, dataset_id, document_id)
        async with distributed_lock(LOCK_DOCUMENT.format(document_id=document_id)):
            doc = await self._get_owned(account_id, dataset_id, document_id)
            async with auto_commit(self.db):
                doc.name = name

    async def update_enabled(self, account_id, dataset_id, document_id, enabled: bool):
        async with distributed_lock(LOCK_DOCUMENT.format(document_id=document_id)):
            doc = await self._get_owned(account_id, dataset_id, document_id)
            if doc.status != DocumentStatus.COMPLETE:
                raise FailException("当前文档处于不可修改状态，请稍后重试")
            if doc.enabled == enabled:
                raise FailException(f"当前文档已是{'启用' if enabled else '禁用'}状态")

            async with auto_commit(self.db):
                doc.enabled = enabled
                doc.disabled_at = None if enabled else datetime.now()

            # 同步 document_enabled 到 Weaviate 所有 segment
            result = await self.db.execute(
                select(Segment.id, Segment.node_id).where(
                    Segment.document_id == document_id, Segment.enabled == True
                )
            )
            rows = result.all()
            seg_ids = [str(r[0]) for r in rows]
            node_ids = [str(r[1]) for r in rows]

            if node_ids:
                try:
                    await VectorService.update_document_enabled(node_ids, enabled)
                except WeaviateBaseError:
                    logger.warning("同步向量库文档启用状态失败 document_id=%s", document_id, exc_info=True)

            # 同步关键词倒排表（加数据集级锁）
            if seg_ids:
                async with distributed_lock(LOCK_DATASET.format(dataset_id=str(dataset_id))):
                    async with auto_commit(self.db):
                        if enabled:
                            await KeywordTableService(self.db).add_keyword_table_from_ids(str(dataset_id), seg_ids)
                        else:
                            await KeywordTableService(self.db).delete_keyword_table_from_ids(str(dataset_id), seg_ids)

    async def delete_document(self, account_id, dataset_id, document_id):
        async with distributed_lock(LOCK_DOCUMENT.format(document_id=document_id), expire=120):
            doc = await self._get_owned(account_id, dataset_id, document_id)
            if doc.status not in (DocumentStatus.COMPLETE, DocumentStatus.ERROR):
                raise FailException("当前文档处于不可删除状态，请稍后重试")

            seg_result = await self.db.execute(select(Segment.id).where(Segment.document_id == document_id))
            seg_ids = [str(s.id) for s in seg_result.all()]

            try:
                await VectorService.delete_by_document(str(document_id))
            except WeaviateBaseError:
                logger.warning("向量库删除文档失败 document_id=%s", document_id, exc_info=True)

            # 删关键词倒排表 + PG 记录（数据集级锁保护倒排表）
            async with distributed_lock(LOCK_DATASET.format(dataset_id=str(dataset_id))):
                async with auto_commit(self.db):
                    if seg_ids:
                        await KeywordTableService(self.db).delete_keyword_table_from_ids(str(dataset_id), seg_ids)
                    await self.db.execute(delete(Segment).where(Segment.document_id == document_id))
                    process_rule_id = doc.process_rule_id
                    await self.db.delete(doc)
                    await self.db.flush()
                    if process_rule_id:
                        remaining = (await self.db.execute(
                            select(func.count(Document.id)).where(Document.process_rule_id == process_rule_id)
                        )).scalar()
                        if remaining == 0:
                            await self.db.execute(delete(ProcessRule).where(ProcessRule.id == process_rule_id))

    async def documents_by_batch(self, account_id, dataset_id, batch: str) -> Sequence[Document]:
        result = await self.db.execute(
            select(Document)
            .where(Document.account_id == account_id, Document.dataset_id == dataset_id, Document.batch == batch)
            .order_by(Document.position)
        )
        return result.scalars().all()

    async def doc_stats(self, document_id) -> dict:
        seg_count = (await self.db.execute(
            select(func.count(Segment.id)).where(Segment.document_id == document_id)
        )).scalar() or 0
        hit_count = (await self.db.execute(
            select(func.coalesce(func.sum(Segment.hit_count), 0)).where(Segment.document_id == document_id)
        )).scalar() or 0
        return {"segment_count": seg_count, "hit_count": hit_count}

    async def batch_doc_stats(self, document_ids: list[str]) -> dict[str, dict]:
        q = select(
            Segment.document_id,
            func.count(Segment.id).label("seg_count"),
            func.coalesce(func.sum(Segment.hit_count), 0).label("hit_count"),
        ).where(Segment.document_id.in_(document_ids)).group_by(Segment.document_id)
        rows = (await self.db.execute(q)).all()
        stats = {doc_id: {"segment_count": 0, "hit_count": 0} for doc_id in document_ids}
        for doc_id, seg_count, hit_count in rows:
            stats[str(doc_id)] = {"segment_count": seg_count, "hit_count": hit_count}
        return stats

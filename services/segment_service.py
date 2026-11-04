import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from weaviate.exceptions import WeaviateBaseError

from core.database import auto_commit
from entity.dataset_entity import DocumentStatus, SegmentStatus
from utils.lock import LOCK_DOCUMENT, LOCK_DATASET, distributed_lock
from utils.exception import FailException, NotFoundException
from utils.security import generate_text_hash
from models import Document, Segment
from schemas.common import PageData, make_paginator
from schemas.dataset import CreateSegmentReq, UpdateSegmentReq
from services.embedding_service import EmbeddingService
from services.jieba_service import JiebaService
from services.keyword_table_service import KeywordTableService
from services.vector_service import VectorService

logger = logging.getLogger(__name__)


class SegmentService:
    """片段服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_owned(self, account_id, dataset_id, document_id, segment_id) -> Segment:
        seg = await self.db.get(Segment, segment_id)
        if (
            not seg
            or seg.account_id != account_id
            or str(seg.dataset_id) != str(dataset_id)
            or str(seg.document_id) != str(document_id)
        ):
            raise NotFoundException("片段不存在")
        return seg

    async def _refresh_document_stats(self, doc_id):
        """文档增删 segment 后，重算其 character_count / token_count"""
        result = await self.db.execute(
            select(
                func.coalesce(func.sum(Segment.character_count), 0),
                func.coalesce(func.sum(Segment.token_count), 0),
            ).where(Segment.document_id == doc_id)
        )
        total = result.one()
        doc = await self.db.get(Document, doc_id)
        if doc:
            doc.character_count = total[0]
            doc.token_count = total[1]

    async def create_segment(self, account_id, dataset_id, document_id, req: CreateSegmentReq):
        token_count = EmbeddingService.count_tokens(req.content)
        if token_count > 1000:
            raise FailException("上传的内容token长度超过1000限制，请核实后重试")

        async with distributed_lock(LOCK_DOCUMENT.format(document_id=document_id)):
            doc = await self.db.get(Document, document_id)
            if not doc or str(doc.account_id) != str(account_id) or str(doc.dataset_id) != str(dataset_id):
                raise NotFoundException("文档不存在")
            if doc.status != DocumentStatus.COMPLETE:
                raise FailException("该知识库文档正在处理中，请稍等后再试")

            pos_result = await self.db.execute(
                select(func.coalesce(func.max(Segment.position), 0)).where(Segment.document_id == document_id)
            )
            position = pos_result.scalar() or 0

            keywords = req.keywords or JiebaService.extract_keywords(req.content, 10)
            if len(keywords) > 10:
                keywords = keywords[:10]
            keywords = list(dict.fromkeys(keywords))

            node_id = uuid.uuid4()
            text_hash = generate_text_hash(req.content)

            seg = Segment(
                account_id=account_id,
                dataset_id=dataset_id,
                document_id=document_id,
                node_id=node_id,
                position=position + 1,
                content=req.content,
                character_count=len(req.content),
                token_count=token_count,
                keywords=keywords,
                hash=text_hash,
                enabled=True,
                status=SegmentStatus.COMPLETE,
                processing_started_at=datetime.now(),
                indexing_completed_at=datetime.now(),
                completed_at=datetime.now(),
            )

            try:
                async with auto_commit(self.db):
                    self.db.add(seg)
                    await self.db.flush()

                    vec = await EmbeddingService.embed_query(req.content)
                    await VectorService.add_segment(
                        str(node_id), req.content, vec,
                        {
                            "account_id": str(account_id),
                            "dataset_id": str(dataset_id),
                            "document_id": str(document_id),
                            "segment_id": str(seg.id),
                            "node_id": str(node_id),
                            "document_enabled": doc.enabled,
                            "segment_enabled": True,
                        },
                    )

                    await self._refresh_document_stats(document_id)

                if doc.enabled:
                    async with distributed_lock(LOCK_DATASET.format(dataset_id=str(dataset_id))):
                        async with auto_commit(self.db):
                            await KeywordTableService(self.db).add_keyword_table_from_ids(
                                str(dataset_id), [str(seg.id)]
                            )
            except SQLAlchemyError:
                logger.exception("创建文档片段失败")
                if seg and seg.id:
                    async with auto_commit(self.db):
                        seg.error = str(e)[:500]
                        seg.status = SegmentStatus.ERROR
                        seg.enabled = False
                        seg.disabled_at = datetime.now()
                        seg.stopped_at = datetime.now()
                raise FailException("创建文档片段失败，请稍后尝试")

    async def list_segments(self, account_id, dataset_id, document_id, current_page, page_size, search_key="") -> PageData:
        q = select(Segment).where(
            Segment.account_id == account_id,
            Segment.dataset_id == dataset_id,
            Segment.document_id == document_id,
        )
        if search_key:
            q = q.where(Segment.content.ilike(f"%{search_key}%"))
        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0
        rows_q = q.order_by(Segment.position).offset((current_page - 1) * page_size).limit(page_size)
        rows = (await self.db.execute(rows_q)).scalars().all()
        return PageData(items=rows, paginator=make_paginator(total, current_page, page_size))

    async def get_segment(self, account_id, dataset_id, document_id, segment_id) -> Segment:
        return await self._get_owned(account_id, dataset_id, document_id, segment_id)

    async def update_segment(self, account_id, dataset_id, document_id, segment_id, req: UpdateSegmentReq):
        async with distributed_lock(LOCK_DOCUMENT.format(document_id=document_id)):
            seg = await self._get_owned(account_id, dataset_id, document_id, segment_id)
            if seg.status != SegmentStatus.COMPLETE:
                raise FailException("当前片段不可修改状态，请稍后尝试")

            new_content = req.content if req.content is not None else seg.content
            keywords = req.keywords if req.keywords is not None else None
            if keywords is None:
                keywords = JiebaService.extract_keywords(new_content, 10) if req.content is not None else seg.keywords
            if len(keywords) > 10:
                keywords = keywords[:10]
            keywords = list(dict.fromkeys(keywords))

            new_hash = generate_text_hash(new_content)
            content_changed = seg.hash != new_hash

            try:
                async with auto_commit(self.db):
                    seg.content = new_content
                    seg.character_count = len(new_content)
                    seg.token_count = EmbeddingService.count_tokens(new_content)
                    seg.keywords = keywords
                    seg.hash = new_hash

                async with distributed_lock(LOCK_DATASET.format(dataset_id=str(dataset_id))):
                    async with auto_commit(self.db):
                        await KeywordTableService(self.db).delete_keyword_table_from_ids(str(dataset_id), [str(seg.id)])
                        await self.db.flush()
                        await KeywordTableService(self.db).add_keyword_table_from_ids(str(dataset_id), [str(seg.id)])

                if content_changed:
                    vec = await EmbeddingService.embed_query(new_content)
                    if await VectorService.exists(str(seg.node_id)):
                        await VectorService.update_segment_text(str(seg.node_id), new_content, vec)
                    else:
                        doc = await self.db.get(Document, document_id)
                        await VectorService.add_segment(
                            str(seg.node_id), new_content, vec,
                            {
                                "account_id": str(account_id),
                                "dataset_id": str(dataset_id),
                                "document_id": str(document_id),
                                "segment_id": str(seg.id),
                                "node_id": str(seg.node_id),
                                "document_enabled": doc.enabled if doc else False,
                                "segment_enabled": seg.enabled,
                            },
                        )
                    await self._refresh_document_stats(document_id)
            except (SQLAlchemyError, WeaviateBaseError) as e:
                logger.exception("更新文档片段失败: %s", e)
                raise FailException("更新文档片段失败，请稍后尝试")

            return seg

    async def update_enabled(self, account_id, dataset_id, document_id, segment_id, enabled: bool):
        async with distributed_lock(LOCK_DOCUMENT.format(document_id=document_id)):
            seg = await self._get_owned(account_id, dataset_id, document_id, segment_id)
            if seg.status != SegmentStatus.COMPLETE:
                raise FailException("该文档片段正在处理中，请稍等后再试")
            if seg.enabled == enabled:
                raise FailException("该文档片段的启用状态已为该状态，请勿重复操作")

            async with auto_commit(self.db):
                seg.enabled = enabled
                seg.disabled_at = None if enabled else datetime.now()

                doc = await self.db.get(Document, document_id)

            async with distributed_lock(LOCK_DATASET.format(dataset_id=str(dataset_id))):
                async with auto_commit(self.db):
                    if enabled and doc and doc.enabled:
                        await KeywordTableService(self.db).add_keyword_table_from_ids(str(dataset_id), [str(seg.id)])
                    else:
                        await KeywordTableService(self.db).delete_keyword_table_from_ids(str(dataset_id), [str(seg.id)])

        try:
            if await VectorService.exists(str(seg.node_id)):
                await VectorService.update_segment_enabled(str(seg.node_id), enabled)
            else:
                logger.warning("向量库不存在片段对象，跳过启用状态同步, segment_id: %s", segment_id)
        except WeaviateBaseError:
            logger.exception("同步向量库启用状态失败")

    async def delete_segment(self, account_id, dataset_id, document_id, segment_id):
        async with distributed_lock(LOCK_DOCUMENT.format(document_id=document_id)):
            seg = await self._get_owned(account_id, dataset_id, document_id, segment_id)
            if seg.status not in (SegmentStatus.COMPLETE, SegmentStatus.ERROR):
                raise FailException("当前文档片段处于不可删除状态，请稍后尝试")

            async with distributed_lock(LOCK_DATASET.format(dataset_id=str(dataset_id))):
                async with auto_commit(self.db):
                    await KeywordTableService(self.db).delete_keyword_table_from_ids(str(dataset_id), [str(seg.id)])
                    await self.db.delete(seg)
                    await self.db.flush()
                    await self._refresh_document_stats(document_id)

        try:
            await VectorService.delete_by_node_id(str(seg.node_id))
        except WeaviateBaseError:
            logger.warning("向量库删除片段失败 node_id=%s", seg.node_id, exc_info=True)

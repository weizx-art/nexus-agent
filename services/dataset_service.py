import logging
from typing import Sequence

from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from weaviate.exceptions import WeaviateBaseError

from core.database import auto_commit
from entity.dataset_entity import DEFAULT_DATASET_DESCRIPTION, RetrievalSource
from utils.exception import NotFoundException, ValidateErrorException
from models import Dataset, DatasetQuery, Document, KeywordTable, ProcessRule, Segment
from schemas.common import PageData, make_paginator
from services.embedding_service import EmbeddingService
from services.jieba_service import JiebaService
from services.keyword_table_service import KeywordTableService
from services.vector_service import VectorService

logger = logging.getLogger(__name__)


class DatasetService:
    """知识库服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- Dataset CRUD ----------
    async def create_dataset(self, account_id, req):
        result = await self.db.execute(
            select(Dataset).where(Dataset.account_id == account_id, Dataset.name == req.name)
        )
        if result.scalar_one_or_none():
            raise ValidateErrorException(f"名称《{req.name}》已存在")
        description = req.description or DEFAULT_DATASET_DESCRIPTION.format(name=req.name)
        ds = Dataset(account_id=account_id, name=req.name, icon=req.icon, description=description)
        try:
            async with auto_commit(self.db):
                self.db.add(ds)
        except IntegrityError:
            raise ValidateErrorException(f"名称《{req.name}》已存在")
        return ds

    async def get_dataset(self, account_id, dataset_id) -> Dataset:
        ds = await self.db.get(Dataset, dataset_id)
        if not ds or ds.account_id != account_id:
            raise NotFoundException("该知识库不存在")
        return ds

    async def update_dataset(self, account_id, dataset_id, req):
        ds = await self.get_dataset(account_id, dataset_id)
        try:
            async with auto_commit(self.db):
                if req.name is not None and req.name != ds.name:
                    result = await self.db.execute(
                        select(Dataset).where(
                            Dataset.account_id == account_id,
                            Dataset.name == req.name,
                            Dataset.id != dataset_id,
                        )
                    )
                    if result.scalar_one_or_none():
                        raise ValidateErrorException(f"名称《{req.name}》已存在")
                    ds.name = req.name
                if req.icon is not None:
                    ds.icon = req.icon
                if req.description is not None:
                    ds.description = req.description
        except IntegrityError:
            raise ValidateErrorException(f"名称《{req.name}》已存在")

    async def delete_dataset(self, account_id, dataset_id):
        ds = await self.get_dataset(account_id, dataset_id)
        try:
            await VectorService.delete_by_dataset(str(dataset_id))
        except WeaviateBaseError:
            logger.warning("向量库删除数据集失败 dataset_id=%s", dataset_id, exc_info=True)
        async with auto_commit(self.db):
            result = await self.db.execute(select(Document.id).where(Document.dataset_id == dataset_id))
            doc_ids = [row[0] for row in result.all()]
            if doc_ids:
                seg_result = await self.db.execute(
                    select(Segment.id).where(Segment.document_id.in_(doc_ids))
                )
                seg_ids = [str(s.id) for s in seg_result.all()]
                if seg_ids:
                    await KeywordTableService(self.db).delete_keyword_table_from_ids(str(dataset_id), seg_ids)
                await self.db.execute(delete(Segment).where(Segment.document_id.in_(doc_ids)))
                await self.db.execute(delete(Document).where(Document.id.in_(doc_ids)))
            await self.db.execute(delete(ProcessRule).where(ProcessRule.dataset_id == dataset_id))
            await self.db.execute(delete(KeywordTable).where(KeywordTable.dataset_id == dataset_id))
            await self.db.execute(delete(DatasetQuery).where(DatasetQuery.dataset_id == dataset_id))
            await self.db.delete(ds)

    async def list_datasets(self, account_id, current_page, page_size, search_key="") -> PageData:
        q = select(Dataset).where(Dataset.account_id == account_id)
        if search_key:
            q = q.where(Dataset.name.ilike(f"%{search_key}%"))
        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0
        rows_q = q.order_by(desc(Dataset.created_at)).offset((current_page - 1) * page_size).limit(page_size)
        rows = (await self.db.execute(rows_q)).scalars().all()
        return PageData(items=rows, paginator=make_paginator(total, current_page, page_size))

    async def dataset_stats(self, dataset_id) -> dict:
        doc_count = (await self.db.execute(
            select(func.count(Document.id)).where(Document.dataset_id == dataset_id)
        )).scalar() or 0
        char_count = (await self.db.execute(
            select(func.coalesce(func.sum(Document.character_count), 0)).where(Document.dataset_id == dataset_id)
        )).scalar() or 0
        hit_count = (await self.db.execute(
            select(func.coalesce(func.sum(Segment.hit_count), 0)).where(Segment.dataset_id == dataset_id)
        )).scalar() or 0
        return {"document_count": doc_count, "character_count": char_count, "hit_count": hit_count}

    async def batch_dataset_stats(self, dataset_ids: list[str]) -> dict[str, dict]:
        # 将字符串 ID 转换为 UUID 以匹配数据库类型
        from uuid import UUID
        uuid_ids = [UUID(ds_id) for ds_id in dataset_ids]
        
        doc_q = select(
            Document.dataset_id,
            func.count(Document.id).label("doc_count"),
            func.coalesce(func.sum(Document.character_count), 0).label("char_count"),
        ).where(Document.dataset_id.in_(uuid_ids)).group_by(Document.dataset_id)
        hit_q = select(
            Segment.dataset_id,
            func.coalesce(func.sum(Segment.hit_count), 0).label("hit_count"),
        ).where(Segment.dataset_id.in_(uuid_ids)).group_by(Segment.dataset_id)

        doc_rows = (await self.db.execute(doc_q)).all()
        hit_rows = (await self.db.execute(hit_q)).all()

        stats = {}
        for ds_id, doc_count, char_count in doc_rows:
            stats[str(ds_id)] = {"document_count": doc_count, "character_count": char_count, "hit_count": 0}
        for ds_id, hit_count in hit_rows:
            stats.setdefault(str(ds_id), {"document_count": 0, "character_count": 0, "hit_count": 0})
            stats[str(ds_id)]["hit_count"] = hit_count
        for ds_id in dataset_ids:
            stats.setdefault(ds_id, {"document_count": 0, "character_count": 0, "hit_count": 0})
        return stats

    # ---------- 召回测试 ----------
    async def hit(self, account_id, dataset_id, req) -> list[dict]:
        await self.get_dataset(account_id, dataset_id)
        strategy = req.retrieval_strategy
        k = req.k
        score_threshold = req.score

        results: dict[str, dict] = {}

        if strategy in ("semantic", "hybrid"):
            await self._semantic_recall(str(dataset_id), req.query, k, score_threshold, results)

        if strategy in ("full_text", "hybrid"):
            await self._full_text_recall(str(dataset_id), req.query, k, results)

        await self._enrich_hit_results(results, dataset_id, req.query, k)

        return sorted(results.values(), key=lambda x: x["score"], reverse=True)[:k]

    async def _semantic_recall(self, dataset_id: str, query: str, k: int, score_threshold: float, results: dict):
        """向量召回"""
        try:
            query_vector = await EmbeddingService.embed_query(query)
            for r in await VectorService.search(query_vector, dataset_id, k=k, score_threshold=score_threshold):
                sid = r["segment_id"]
                if sid and sid not in results:
                    results[sid] = r
        except (WeaviateBaseError, ValueError) as e:
            logger.warning("向量召回失败: %s", e)

    async def _full_text_recall(self, dataset_id: str, query: str, k: int, results: dict):
        """关键词召回（TF-IDF 提取关键词 + 倒排表匹配）"""
        keywords = JiebaService.extract_keywords(query, top_k=10)
        if not keywords:
            return
        hit_ids = await KeywordTableService(self.db).search_segment_ids(dataset_id, keywords)
        if not hit_ids:
            return
        result = await self.db.execute(
            select(Segment, Document.name)
            .join(Document, Segment.document_id == Document.id)
            .where(
                Segment.dataset_id == dataset_id,
                Segment.enabled.is_(True),
                Segment.id.in_(hit_ids),
            )
        )
        for seg, doc_name in result.all():
            matched = sum(1 for kw in keywords if kw in (seg.keywords or []))
            score = round(matched / len(keywords), 3) if keywords else 0
            sid = str(seg.id)
            if score > 0 and sid not in results:
                results[sid] = {
                    "score": score,
                    "segment_id": sid,
                    "content": seg.content,
                    "document_id": str(seg.document_id),
                    "document_name": doc_name,
                }

    async def _enrich_hit_results(self, results: dict, dataset_id, query: str, k: int):
        """补全 segment 详情字段、累加 hit_count、记录查询"""
        seg_ids = list(results.keys())
        if not seg_ids:
            return

        async with auto_commit(self.db):
            stmt = (
                select(Segment, Document.name)
                .join(Document, Segment.document_id == Document.id)
                .where(Segment.id.in_(seg_ids))
            )
            rows = (await self.db.execute(stmt)).all()
            seg_map = {str(seg.id): (seg, doc_name) for seg, doc_name in rows}

            for sid in seg_ids:
                if sid not in seg_map:
                    results.pop(sid, None)
                    continue
                seg, doc_name = seg_map[sid]
                r = results[sid]
                r.update({
                    "segment_id": sid,
                    "content": seg.content,
                    "document_id": str(seg.document_id),
                    "document_name": doc_name or "",
                    "keywords": seg.keywords or [],
                    "character_count": seg.character_count,
                    "token_count": seg.token_count,
                    "hit_count": seg.hit_count,
                    "position": seg.position,
                    "enabled": seg.enabled,
                    "status": seg.status,
                })
                seg.hit_count += 1

            self.db.add(DatasetQuery(dataset_id=dataset_id, query=query, source=RetrievalSource.HIT_TESTING))

    async def recent_queries(self, account_id, dataset_id) -> Sequence[DatasetQuery]:
        await self.get_dataset(account_id, dataset_id)
        result = await self.db.execute(
            select(DatasetQuery)
            .where(DatasetQuery.dataset_id == dataset_id)
            .order_by(desc(DatasetQuery.created_at))
            .limit(10)
        )
        return result.scalars().all()

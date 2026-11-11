"""统一检索服务：语义 / 全文 / 混合三种策略

召回测试（DatasetService.hit）与对话链路（chat_agent 的 knowledge_retrieval 工具）
共用同一套实现，避免两处召回的过滤条件与打分口径漂移。
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from weaviate.exceptions import WeaviateBaseError

from entity.dataset_entity import RetrievalStrategy
from models import Document, Segment
from services.embedding_service import EmbeddingService
from services.jieba_service import JiebaService
from services.keyword_table_service import KeywordTableService
from services.vector_service import VectorService

logger = logging.getLogger(__name__)

# 混合检索的权重：向量相似度（1 - 余弦距离，约 0~1）与关键词命中率（0~1）同处
# 0~1 区间，直接加权求和，避免两套分数各自归一化后丢失绝对相关度
SEMANTIC_WEIGHT = 0.6
FULL_TEXT_WEIGHT = 0.4

# 全文检索提取的关键词数量，与召回测试保持一致
KEYWORD_TOP_K = 10


class RetrievalService:
    """三策略检索入口（无状态，静态方法）"""

    @classmethod
    async def search(
        cls,
        db: AsyncSession,
        dataset_ids: list[str] | list[uuid.UUID],
        query: str,
        strategy: str = RetrievalStrategy.SEMANTIC,
        k: int = 4,
        score_threshold: float = 0.0,
    ) -> list[dict]:
        """在多个知识库中按指定策略召回，返回按分数倒序的片段列表

        返回项字段：segment_id / document_id / document_name / content / keywords /
        score，以及可选的 semantic_score、full_text_score。
        """
        strategy = RetrievalStrategy(strategy)
        ds_ids = [str(ds_id) for ds_id in dataset_ids]
        if not ds_ids:
            return []

        query_vector = None
        if strategy in (RetrievalStrategy.SEMANTIC, RetrievalStrategy.HYBRID):
            query_vector = await EmbeddingService.embed_query(query)

        keywords: list[str] = []
        if strategy in (RetrievalStrategy.FULL_TEXT, RetrievalStrategy.HYBRID):
            keywords = JiebaService.extract_keywords(query, top_k=KEYWORD_TOP_K)

        merged: dict[str, dict] = {}
        for ds_id in ds_ids:
            semantic: list[dict] = []
            full_text: list[dict] = []
            if query_vector:
                semantic = await cls._semantic_recall(query_vector, ds_id, k, 0.0)
            if keywords:
                full_text = await cls._full_text_recall(db, ds_id, keywords, k, 0.0)

            for item in cls._fuse(semantic, full_text, strategy):
                if item["score"] < score_threshold:
                    continue
                sid = item["segment_id"]
                current = merged.get(sid)
                if current is None or item["score"] > current["score"]:
                    merged[sid] = item

        if not merged:
            return []

        await cls._attach_details(db, merged)
        return sorted(merged.values(), key=lambda x: x["score"], reverse=True)[:k]

    # ---------- 单路召回 ----------

    @staticmethod
    async def _semantic_recall(
        vector: list[float], dataset_id: str, k: int, score_threshold: float
    ) -> list[dict]:
        """向量召回（Weaviate 侧已过滤 document_enabled / segment_enabled）"""
        try:
            rows = await VectorService.search(vector, dataset_id, k=k, score_threshold=score_threshold)
        except (WeaviateBaseError, ValueError) as e:
            logger.warning("向量召回失败 dataset_id=%s: %s", dataset_id, e)
            return []
        return [
            {
                "segment_id": row["segment_id"],
                "document_id": row.get("document_id"),
                "content": row.get("text"),
                "score": float(row.get("score") or 0.0),
            }
            for row in rows
            if row.get("segment_id")
        ]

    @staticmethod
    async def _full_text_recall(
        db: AsyncSession,
        dataset_id: str,
        keywords: list[str],
        k: int,
        score_threshold: float,
    ) -> list[dict]:
        """关键词召回：倒排表命中 segment，再用命中率作为分数"""
        dataset_uuid = uuid.UUID(dataset_id)
        hit_ids = await KeywordTableService(db).search_segment_ids(dataset_uuid, keywords)
        if not hit_ids:
            return []

        seg_ids = [uuid.UUID(sid) for sid in hit_ids]
        rows = (
            await db.execute(
                select(Segment).where(
                    Segment.dataset_id == dataset_uuid,
                    Segment.enabled.is_(True),
                    Segment.id.in_(seg_ids),
                )
            )
        ).scalars().all()

        out: list[dict] = []
        for seg in rows:
            matched = sum(1 for kw in keywords if kw in (seg.keywords or []))
            score = round(matched / len(keywords), 3) if keywords else 0.0
            if score <= 0 or score < score_threshold:
                continue
            out.append(
                {
                    "segment_id": str(seg.id),
                    "document_id": str(seg.document_id),
                    "content": seg.content,
                    "score": score,
                }
            )

        out.sort(key=lambda item: item["score"], reverse=True)
        return out[:k]

    # ---------- 融合 ----------

    @staticmethod
    def _fuse(semantic: list[dict], full_text: list[dict], strategy: RetrievalStrategy) -> list[dict]:
        """按策略组装结果；hybrid 下两路分数按权重直接加权"""
        if strategy == RetrievalStrategy.SEMANTIC:
            return [{**item, "semantic_score": item["score"], "full_text_score": None} for item in semantic]

        if strategy == RetrievalStrategy.FULL_TEXT:
            return [{**item, "semantic_score": None, "full_text_score": item["score"]} for item in full_text]

        fused: dict[str, dict] = {}

        for item in semantic:
            fused[item["segment_id"]] = {
                **item,
                "semantic_score": item["score"],
                "full_text_score": None,
                "score": round(SEMANTIC_WEIGHT * item["score"], 3),
            }

        for item in full_text:
            sid = item["segment_id"]
            if sid in fused:
                fused[sid]["full_text_score"] = item["score"]
                fused[sid]["score"] = round(
                    SEMANTIC_WEIGHT * fused[sid]["semantic_score"] + FULL_TEXT_WEIGHT * item["score"], 3
                )
            else:
                fused[sid] = {
                    **item,
                    "semantic_score": None,
                    "full_text_score": item["score"],
                    "score": round(FULL_TEXT_WEIGHT * item["score"], 3),
                }

        return list(fused.values())

    # ---------- 详情补全 ----------

    @staticmethod
    async def _attach_details(db: AsyncSession, results: dict[str, dict]):
        """用数据库的真实分段信息补全内容与来源，并剔除已停用的文档/分段

        以数据库为准，避免 Weaviate 中 document_enabled / segment_enabled 属性滞后
        导致停用内容仍被召回。
        """
        seg_ids = [uuid.UUID(sid) for sid in results]
        rows = (
            await db.execute(
                select(Segment, Document.name)
                .join(Document, Segment.document_id == Document.id)
                .where(
                    Segment.id.in_(seg_ids),
                    Segment.enabled.is_(True),
                    Document.enabled.is_(True),
                )
            )
        ).all()
        seg_map = {str(seg.id): (seg, doc_name) for seg, doc_name in rows}

        for sid in list(results):
            if sid not in seg_map:
                results.pop(sid)
                continue
            seg, doc_name = seg_map[sid]
            results[sid].update(
                {
                    "segment_id": sid,
                    "document_id": str(seg.document_id),
                    "content": seg.content,
                    "document_name": doc_name or "",
                    "keywords": seg.keywords or [],
                }
            )

import asyncio
import functools
import logging
import threading
from typing import Any

import weaviate
from weaviate.exceptions import WeaviateBaseError

logger = logging.getLogger(__name__)
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.init import Auth
from weaviate.classes.query import Filter

from core.config import settings

COLLECTION_NAME = "Dataset"


class VectorService:
    """Weaviate 向量数据库服务（异步）。"""

    _client = None
    _lock = threading.Lock()

    @classmethod
    def client(cls) -> weaviate.WeaviateClient:
        """同步客户端（仅用于初始化和 schema 操作），带重试机制"""
        if cls._client is None:
            with cls._lock:
                if cls._client is None:
                    host = settings.WEAVIATE_URL.replace("http://", "").split(":")[0]
                    auth = Auth.api_key(settings.WEAVIATE_API_KEY) if settings.WEAVIATE_API_KEY else None
                    
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            cls._client = weaviate.connect_to_custom(
                                http_host=host,
                                http_port=8080,
                                http_secure=False,
                                grpc_host=host,
                                grpc_port=50051,
                                grpc_secure=False,
                                auth_credentials=auth,
                            )
                            cls._ensure_collection()
                            logger.info("Weaviate 连接成功")
                            break
                        except WeaviateBaseError as e:
                            if attempt < max_retries - 1:
                                wait = 2 ** attempt
                                logger.warning("Weaviate 连接失败 (第%d次)，%d秒后重试: %s", attempt + 1, wait, e)
                                import time
                                time.sleep(wait)
                            else:
                                logger.error("Weaviate 连接失败，已重试%d次: %s", max_retries, e)
                                raise
        return cls._client

    @classmethod
    def _ensure_collection(cls):
        if cls._client.collections.exists(COLLECTION_NAME):
            return
        cls._client.collections.create(
            name=COLLECTION_NAME,
            vectorizer_config=Configure.Vectorizer.none(),
            properties=[
                Property(name="text", data_type=DataType.TEXT),
                Property(name="account_id", data_type=DataType.TEXT),
                Property(name="dataset_id", data_type=DataType.TEXT),
                Property(name="document_id", data_type=DataType.TEXT),
                Property(name="segment_id", data_type=DataType.TEXT),
                Property(name="node_id", data_type=DataType.TEXT),
                Property(name="document_enabled", data_type=DataType.BOOL),
                Property(name="segment_enabled", data_type=DataType.BOOL),
            ],
        )

    @classmethod
    def collection(cls):
        return cls.client().collections.get(COLLECTION_NAME)

    @classmethod
    async def _run_sync(cls, func, *args, **kwargs):
        """在线程池中执行同步的 Weaviate 调用，避免阻塞 event loop"""
        if kwargs:
            func = functools.partial(func, **kwargs)
        return await asyncio.to_thread(func, *args)

    @classmethod
    async def add_segment(cls, node_id: str, text: str, vector: list[float], props: dict[str, Any]):
        await cls._run_sync(
            cls.collection().data.insert,
            uuid=node_id,
            properties={"text": text, **props},
            vector=vector,
        )

    @classmethod
    async def search(cls, vector: list[float], dataset_id: str, k: int = 4, score_threshold: float = 0.0) -> list[dict]:
        res = await cls._run_sync(
            cls.collection().query.near_vector,
            near_vector=vector,
            limit=k,
            filters=Filter.by_property("dataset_id").equal(dataset_id)
            & Filter.by_property("document_enabled").equal(True)
            & Filter.by_property("segment_enabled").equal(True),
            return_metadata=["distance"],
        )
        out = []
        for o in res.objects:
            d = o.properties
            score = 1 - (o.metadata.distance or 0)
            if score < score_threshold:
                continue
            out.append({
                "segment_id": d.get("segment_id"),
                "document_id": d.get("document_id"),
                "text": d.get("text"),
                "score": round(score, 3),
            })
        return out

    @classmethod
    async def delete_by_document(cls, document_id: str):
        await cls._run_sync(
            cls.collection().data.delete_many,
            where=Filter.by_property("document_id").equal(document_id),
        )

    @classmethod
    async def delete_by_dataset(cls, dataset_id: str):
        await cls._run_sync(
            cls.collection().data.delete_many,
            where=Filter.by_property("dataset_id").equal(dataset_id),
        )

    @classmethod
    async def delete_by_node_id(cls, node_id: str):
        try:
            await cls._run_sync(cls.collection().data.delete_by_id, node_id)
        except WeaviateBaseError:
            logger.warning("向量删除失败 node_id=%s", node_id, exc_info=True)

    @classmethod
    async def update_segment_enabled(cls, node_id: str, enabled: bool):
        try:
            await cls._run_sync(
                cls.collection().data.update,
                uuid=node_id,
                properties={"segment_enabled": enabled},
            )
        except WeaviateBaseError:
            logger.warning("向量更新 segment_enabled 失败 node_id=%s", node_id, exc_info=True)

    @classmethod
    async def update_document_enabled(cls, node_ids: list[str], enabled: bool):
        """批量更新给定 node_ids 的 document_enabled 字段"""
        if not node_ids:
            return
        
        # 批量并行更新
        tasks = [
            cls._run_sync(
                cls.collection().data.update,
                uuid=nid,
                properties={"document_enabled": enabled},
            )
            for nid in node_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 记录失败的更新
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("批量更新 document_enabled 失败 (node_id=%s): %s", node_ids[i], result)

    @classmethod
    async def update_node_properties(cls, node_id: str, properties: dict):
        """更新单个节点的多个属性"""
        try:
            await cls._run_sync(
                cls.collection().data.update,
                uuid=node_id,
                properties=properties,
            )
        except WeaviateBaseError:
            logger.warning("向量更新属性失败 node_id=%s", node_id, exc_info=True)

    @classmethod
    async def update_segment_text(cls, node_id: str, text: str, vector: list[float]):
        try:
            await cls._run_sync(
                cls.collection().data.update,
                uuid=node_id,
                properties={"text": text},
                vector=vector,
            )
        except WeaviateBaseError:
            logger.warning("向量更新文本失败 node_id=%s", node_id, exc_info=True)

    @classmethod
    async def exists(cls, node_id: str) -> bool:
        """检查向量对象是否存在"""
        try:
            return await cls._run_sync(cls.collection().data.exists, uuid=node_id)
        except WeaviateBaseError:
            logger.warning("向量存在检查失败 node_id=%s", node_id, exc_info=True)
            return False

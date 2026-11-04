import asyncio
import hashlib
import json
import logging
import os
import threading
from typing import Any

import tiktoken
from redis.exceptions import RedisError

from cache.redis import get_redis
from core.config import settings

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

logger = logging.getLogger(__name__)


class EmbeddingService:
    """文本嵌入服务：本地 HuggingFace 模型 + Redis 向量缓存。懒加载，首次调用才下载。"""

    _embeddings = None
    _lock = threading.Lock()
    _model_hash = hashlib.md5(settings.EMBEDDING_MODEL_NAME.encode()).hexdigest()[:8]

    @classmethod
    def _load(cls):
        if cls._embeddings is not None:
            return
        with cls._lock:
            if cls._embeddings is not None:
                return
            from langchain_huggingface import HuggingFaceEmbeddings

            cls._embeddings = HuggingFaceEmbeddings(
                model_name=settings.EMBEDDING_MODEL_NAME,
                model_kwargs={"trust_remote_code": True},
                encode_kwargs={"normalize_embeddings": True},
            )
            logger.info("Embedding 模型加载完成: %s", settings.EMBEDDING_MODEL_NAME)

    @classmethod
    def _cache_key(cls, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"emb:{cls._model_hash}:{digest}"

    @classmethod
    async def _embed_cached(cls, text: str) -> list[float]:
        """带 Redis 缓存的单条文本向量化"""
        r = await get_redis()
        key = cls._cache_key(text)
        cached = await r.get(key)
        if cached is not None:
            return json.loads(cached)

        await asyncio.to_thread(cls._load)
        vector = await asyncio.to_thread(cls._embeddings.embed_query, text)
        try:
            await r.set(key, json.dumps(vector), ex=86400 * 7)
        except RedisError:
            logger.warning("Redis 缓存写入失败 key=%s", key, exc_info=True)
        return vector

    @classmethod
    async def embed_query(cls, text: str) -> list[float]:
        return await cls._embed_cached(text)

    @classmethod
    async def embed_documents(cls, texts: list[str]) -> tuple[Any]:
        return await asyncio.gather(*[cls._embed_cached(t) for t in texts])

    @staticmethod
    def count_tokens(text: str) -> int:
        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text))

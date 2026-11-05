import warnings

warnings.simplefilter("ignore", ResourceWarning)

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from core.config import settings
from core.database import Base, engine
from cache.redis import close_redis
from utils.exception import register_exception_handlers
from routers import test, account, auth, dataset, upload_file, chat

# import models 以确保建表时全部注册
import models  # noqa: F401

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("weaviate").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.WARNING)
logging.getLogger("torch").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("aiobotocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("multipart").setLevel(logging.WARNING)
logging.getLogger("jieba").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("应用启动中...")
    settings.validate_production()
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.debug("数据库表结构已检查")

    await asyncio.to_thread(_warmup_jieba)
    await asyncio.to_thread(_warmup_weaviate)

    yield
    await asyncio.to_thread(_close_weaviate)
    await close_redis()
    await engine.dispose()
    logger.info("应用已关闭，资源已释放")


def _warmup_jieba():
    """预热 jieba 分词"""
    try:
        import jieba
        jieba.initialize()
        logger.info("jieba 分词词典预热完成")
    except ImportError:
        logger.warning("jieba 预热失败")


def _warmup_weaviate():
    """预热 Weaviate 连接"""
    from services.vector_service import VectorService
    try:
        VectorService.client()
        logger.info("Weaviate 连接预热完成")
    except Exception:
        logger.warning("Weaviate 预热失败", exc_info=True)


def _close_weaviate():
    from services.vector_service import VectorService
    try:
        if VectorService._client:
            VectorService._client.close()
            VectorService._client = None
    except Exception:
        logger.warning("Weaviate 关闭失败", exc_info=True)


app = FastAPI(
    title=settings.APP_NAME, docs_url="/docs", redoc_url="/redoc", lifespan=lifespan
)

origins = settings.cors_origins_list
app.add_middleware(  # type: ignore
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)  # type: ignore


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response

register_exception_handlers(app)

app.include_router(test.router, prefix=settings.API_PREFIX)
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(account.router, prefix=settings.API_PREFIX)
app.include_router(upload_file.router, prefix=settings.API_PREFIX)
app.include_router(chat.router, prefix=settings.API_PREFIX)
app.include_router(dataset.router, prefix=settings.API_PREFIX)

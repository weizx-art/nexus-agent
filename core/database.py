import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""


engine = create_async_engine(
    settings.DATABASE_URI,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

logger.info("数据库引擎已创建: pool_size=10, max_overflow=20")


async def get_db():
    """FastAPI 依赖：请求级异步数据库会话"""
    async with AsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()


@asynccontextmanager
async def auto_commit(db: AsyncSession):
    """异步事务管理：正常退出自动 commit，异常自动 rollback 并抛出"""
    try:
        yield
        await db.commit()
    except Exception:
        await db.rollback()
        raise

import logging
from fastapi import APIRouter
from sqlalchemy import text

from core.database import AsyncSessionLocal
from cache.redis import get_redis

router = APIRouter(prefix="/ping", tags=["测试"])
logger = logging.getLogger(__name__)


@router.get("")
async def ping():
    """简单健康检查"""
    return {"code": "success", "message": "", "data": {"msg": "pong"}}


@router.get("/health")
async def health_check():
    """详细健康检查：数据库 + Redis"""
    status = {"status": "healthy", "checks": {}}
    
    # 检查数据库
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        status["checks"]["database"] = "connected"
    except Exception as e:
        logger.error("数据库健康检查失败: %s", e)
        status["checks"]["database"] = f"error: {str(e)}"
        status["status"] = "unhealthy"
    
    # 检查 Redis
    try:
        redis = await get_redis()
        await redis.ping()
        status["checks"]["redis"] = "connected"
    except Exception as e:
        logger.error("Redis 健康检查失败: %s", e)
        status["checks"]["redis"] = f"error: {str(e)}"
        status["status"] = "unhealthy"
    
    return {"code": "success", "message": "", "data": status}

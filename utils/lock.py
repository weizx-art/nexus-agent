import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from cache.redis import get_redis
from utils.exception import FailException

DEFAULT_TIMEOUT = 10
DEFAULT_EXPIRE = 60

LOCK_DOCUMENT = "lock:document:{document_id}"
LOCK_DATASET = "lock:dataset:{dataset_id}"


@asynccontextmanager
async def distributed_lock(key: str, timeout: float = DEFAULT_TIMEOUT, expire: int = DEFAULT_EXPIRE):
    """Redis 分布式锁上下文管理器。

    - 在 timeout 秒内重试获取锁，超时抛 FailException
    - 锁自动在 expire 秒后过期（防止持有者崩溃导致死锁）
    - 使用唯一 value 确保只释放自己持有的锁
    """
    redis = await get_redis()
    lock_value = str(uuid.uuid4())
    acquired = False

    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = await redis.set(key, lock_value, nx=True, ex=expire)
            if result:
                acquired = True
                break
            await asyncio.sleep(0.1)

        if not acquired:
            raise FailException("操作冲突，系统正在处理中，请稍后重试")

        yield
    finally:
        if acquired:
            # 只释放自己持有的锁（防止误删别人的锁）
            lua = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            end
            return 0
            """
            await redis.eval(lua, 1, key, lock_value)

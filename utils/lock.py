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
    """Redis 分布式锁上下文管理器，带自动续期。

    - 在 timeout 秒内重试获取锁，超时抛 FailException
    - 锁自动在 expire 秒后过期（防止持有者崩溃导致死锁）
    - 使用唯一 value 确保只释放自己持有的锁
    - 后台任务每 expire/3 秒续期一次，防止长任务锁过期
    """
    redis = await get_redis()
    lock_value = str(uuid.uuid4())
    acquired = False
    renew_task: asyncio.Task | None = None

    async def _renew_lock():
        """后台续期任务"""
        try:
            interval = expire / 3
            while True:
                await asyncio.sleep(interval)
                lua = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("expire", KEYS[1], ARGV[2])
                end
                return 0
                """
                await redis.eval(lua, 1, key, lock_value, expire)
        except asyncio.CancelledError:
            pass

    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = await redis.set(key, lock_value, nx=True, ex=expire)
            if result:
                acquired = True
                renew_task = asyncio.create_task(_renew_lock())
                break
            await asyncio.sleep(0.1)

        if not acquired:
            raise FailException("操作冲突，系统正在处理中，请稍后重试")

        yield
    finally:
        if renew_task:
            renew_task.cancel()
            try:
                await renew_task
            except asyncio.CancelledError:
                pass
        if acquired:
            lua = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            end
            return 0
            """
            await redis.eval(lua, 1, key, lock_value)

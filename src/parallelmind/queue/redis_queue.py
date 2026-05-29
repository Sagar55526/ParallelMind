from redis.asyncio import Redis

from parallelmind.models import Task, TaskStatus
from parallelmind.queue.base import QueueEmpty, TaskQueue


class RedisTaskQueue(TaskQueue):
    """LIST-backed FIFO: LPUSH on the head, BRPOP on the tail."""

    def __init__(self, redis: Redis, queue_name: str) -> None:
        self._redis = redis
        self._key = queue_name
        self._closed = False

    @classmethod
    def from_url(cls, url: str, queue_name: str, max_connections: int = 32) -> "RedisTaskQueue":
        client = Redis.from_url(url, max_connections=max_connections, decode_responses=False)
        return cls(client, queue_name)

    async def put(self, task: Task) -> None:
        if self._closed:
            raise RuntimeError("queue is closed")
        if task.status != TaskStatus.QUEUED:
            task.transition_to(TaskStatus.QUEUED)
        await self._redis.lpush(self._key, task.to_json())

    async def get(self, timeout: float | None = None) -> Task:
        # redis-py treats timeout=0 as "block forever".
        result = await self._redis.brpop([self._key], timeout=timeout or 0)
        if result is None:
            raise QueueEmpty(f"no task in '{self._key}' within {timeout}s")
        _key, raw = result
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return Task.from_json(raw)

    async def size(self) -> int:
        return await self._redis.llen(self._key)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._redis.aclose()

    async def clear(self) -> None:
        """Test helper: drop all tasks."""
        await self._redis.delete(self._key)

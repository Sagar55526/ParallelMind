import asyncio

from parallelmind.models import Task, TaskStatus
from parallelmind.queue.base import QueueEmpty, QueueFull, TaskQueue


class InMemoryTaskQueue(TaskQueue):
    def __init__(self, maxsize: int = 0) -> None:
        self._q: asyncio.Queue[Task] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    async def put(self, task: Task) -> None:
        if self._closed:
            raise RuntimeError("queue is closed")
        # The queue owns the -> QUEUED transition.
        if task.status != TaskStatus.QUEUED:
            task.transition_to(TaskStatus.QUEUED)
        try:
            self._q.put_nowait(task)
        except asyncio.QueueFull as e:
            raise QueueFull(f"queue at capacity ({self._q.maxsize})") from e

    async def get(self, timeout: float | None = None) -> Task:
        if self._closed and self._q.empty():
            raise QueueEmpty("queue is closed and empty")
        if timeout is None:
            return await self._q.get()
        try:
            return await asyncio.wait_for(self._q.get(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise QueueEmpty(f"no task available within {timeout}s") from e

    async def size(self) -> int:
        return self._q.qsize()

    async def close(self) -> None:
        self._closed = True

from parallelmind.models import Task


class QueueEmpty(Exception):
    """Raised by get() when timeout elapses with no task available."""


class QueueFull(Exception):
    """Raised by put() when a bounded queue is at capacity."""


class TaskQueue:
    """Subclasses override these methods."""

    async def put(self, task: Task) -> None:
        raise NotImplementedError

    async def get(self, timeout: float | None = None) -> Task:
        raise NotImplementedError

    async def size(self) -> int:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

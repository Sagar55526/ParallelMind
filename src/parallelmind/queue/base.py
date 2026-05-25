from __future__ import annotations

from typing import Protocol, runtime_checkable

from parallelmind.models import Task


class QueueEmpty(Exception):
    """Raised by `get` when timeout elapses with no task available."""


class QueueFull(Exception):
    """Raised by `put` when a bounded queue is at capacity."""


@runtime_checkable
class TaskQueue(Protocol):
    async def put(self, task: Task) -> None: ...
    async def get(self, timeout: float | None = None) -> Task: ...
    async def size(self) -> int: ...
    async def close(self) -> None: ...

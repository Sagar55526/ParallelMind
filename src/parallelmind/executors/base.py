from typing import Any

from parallelmind.models import Task


class ExecutorError(Exception):
    """Raised by an executor when the task fails for a domain-level reason."""


class AsyncTaskExecutor:
    """Implement when the work is async-native (uses await internally)."""

    async def execute(self, task: Task) -> Any:
        raise NotImplementedError


class SyncTaskExecutor:
    """Implement when the work is blocking — sync IO or pure CPU.

    Required to be picklable if used with ProcessBackend (no closures, no
    references to non-importable objects).
    """

    def execute(self, task: Task) -> Any:
        raise NotImplementedError

from typing import Any

from parallelmind.models import Task, TaskKind


class ExecutorError(Exception):
    """Raised by an executor when the task fails for a domain-level reason."""


class TaskExecutor:
    """Subclasses override execute()."""

    async def execute(self, task: Task) -> Any:
        raise NotImplementedError


class ExecutorRegistry:
    """Dispatch table: TaskKind -> TaskExecutor."""

    def __init__(self) -> None:
        self._by_kind: dict[TaskKind, TaskExecutor] = {}

    def register(self, kind: TaskKind, executor: TaskExecutor) -> None:
        self._by_kind[kind] = executor

    def resolve(self, kind: TaskKind) -> TaskExecutor:
        if kind not in self._by_kind:
            raise ExecutorError(f"no executor registered for kind={kind}")
        return self._by_kind[kind]

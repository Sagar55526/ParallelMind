from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from parallelmind.models import Task, TaskKind


class ExecutorError(Exception):
    """Raised by an executor when the task fails for a domain-level reason."""


@runtime_checkable
class TaskExecutor(Protocol):
    """Knows how to run a Task and return its result."""

    async def execute(self, task: Task) -> Any: ...


class ExecutorRegistry:
    """Dispatch table: TaskKind -> TaskExecutor."""

    def __init__(self) -> None:
        self._by_kind: dict[TaskKind, TaskExecutor] = {}

    def register(self, kind: TaskKind, executor: TaskExecutor) -> None:
        self._by_kind[kind] = executor

    def resolve(self, kind: TaskKind) -> TaskExecutor:
        try:
            return self._by_kind[kind]
        except KeyError as e:
            raise ExecutorError(f"no executor registered for kind={kind}") from e

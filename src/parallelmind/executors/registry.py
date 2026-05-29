from parallelmind.executors.backends import Backend
from parallelmind.executors.base import ExecutorError
from parallelmind.models import TaskKind


class ExecutorRegistry:
    """Dispatch table: TaskKind -> (executor, backend)."""

    def __init__(self) -> None:
        self._by_kind: dict = {}

    def register(self, kind: TaskKind, executor, backend: Backend) -> None:
        self._by_kind[kind] = (executor, backend)

    def resolve(self, kind: TaskKind):
        if kind not in self._by_kind:
            raise ExecutorError(f"no executor registered for kind={kind}")
        return self._by_kind[kind]  # (executor, backend)

    def backends(self) -> list[Backend]:
        """Distinct backend instances — useful for shutdown."""
        seen: list[Backend] = []
        for _executor, backend in self._by_kind.values():
            if backend not in seen:
                seen.append(backend)
        return seen

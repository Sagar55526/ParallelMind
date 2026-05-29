import asyncio

from parallelmind.executors.registry import ExecutorRegistry
from parallelmind.observability.logging import get_logger
from parallelmind.queue.base import TaskQueue
from parallelmind.workers.async_worker import run_worker

log = get_logger(__name__)


class Dispatcher:
    """Owns N async workers consuming from a single queue."""

    def __init__(
        self,
        queue: TaskQueue,
        registry: ExecutorRegistry,
        worker_count: int,
        on_finished=None,  # async (Task) -> None
        poll_timeout: float = 1.0,
    ) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be >= 1")
        self._queue = queue
        self._registry = registry
        self._worker_count = worker_count
        self._on_finished = on_finished
        self._poll_timeout = poll_timeout
        self._workers: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        if self._running:
            raise RuntimeError("dispatcher already running")
        self._running = True
        self._workers = [
            asyncio.create_task(
                run_worker(
                    worker_id=f"worker-{i}",
                    queue=self._queue,
                    registry=self._registry,
                    poll_timeout=self._poll_timeout,
                    on_finished=self._on_finished,
                ),
                name=f"parallelmind-worker-{i}",
            )
            for i in range(self._worker_count)
        ]
        log.info("dispatcher_started", workers=self._worker_count)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        for w in self._workers:
            w.cancel()

        # gather() with return_exceptions=True so one bad worker doesn't mask the others.
        results = await asyncio.gather(*self._workers, return_exceptions=True)
        unexpected = 0
        for r in results:
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                log.exception("worker_failed_during_shutdown", error=str(r))
                unexpected += 1
        self._workers = []
        log.info("dispatcher_stopped", unexpected_errors=unexpected)

    @property
    def is_running(self) -> bool:
        return self._running

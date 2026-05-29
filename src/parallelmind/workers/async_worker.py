import asyncio

from parallelmind.executors.base import ExecutorRegistry
from parallelmind.models import TaskStatus
from parallelmind.observability.logging import get_logger
from parallelmind.queue.base import QueueEmpty, TaskQueue

log = get_logger(__name__)


async def run_worker(
    worker_id: str,
    queue: TaskQueue,
    registry: ExecutorRegistry,
    poll_timeout: float = 1.0,
    on_finished=None,  # async (Task) -> None
) -> None:
    """Single worker loop: get -> execute -> update state -> repeat until cancelled."""
    wlog = log.bind(worker=worker_id)
    wlog.info("worker_started")

    try:
        while True:
            try:
                task = await queue.get(timeout=poll_timeout)
            except QueueEmpty:
                continue  # idle tick, loop and BRPOP again

            tlog = wlog.bind(task_id=str(task.id), kind=task.kind.value)
            task.transition_to(TaskStatus.RUNNING)
            tlog.info("task_running", attempt=task.attempts)

            try:
                executor = registry.resolve(task.kind)
                result = await executor.execute(task)
                task.payload["_result"] = result
                task.transition_to(TaskStatus.SUCCESS)
                tlog.info("task_success")
            except asyncio.CancelledError:
                # Shutting down — leave the task in RUNNING for Phase 2 recovery.
                tlog.warning("task_cancelled_mid_run")
                raise
            except Exception as exc:
                task.transition_to(TaskStatus.FAILED, error=str(exc))
                tlog.exception("task_failed")

            if on_finished is not None:
                await on_finished(task)
    except asyncio.CancelledError:
        wlog.info("worker_cancelled")
        raise

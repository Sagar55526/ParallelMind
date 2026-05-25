from __future__ import annotations

import asyncio
from collections.abc import Callable

from parallelmind.executors.base import ExecutorRegistry
from parallelmind.models import Task, TaskStatus
from parallelmind.observability.logging import get_logger
from parallelmind.queue.base import QueueEmpty, TaskQueue

log = get_logger(__name__)

# Callback signature: invoked after each terminal transition so the dispatcher
# (or tests) can observe execution without coupling the worker to a repo.
TaskHook = Callable[[Task], "asyncio.Future[None] | None"]


async def run_worker(
    worker_id: str,
    queue: TaskQueue,
    registry: ExecutorRegistry,
    *,
    poll_timeout: float = 1.0,
    on_finished: TaskHook | None = None,
) -> None:
    """Single worker loop: get → execute → update state → repeat until cancelled."""
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
                # Worker is shutting down. Don't mark task SUCCESS/FAILED —
                # leave it RUNNING so the recovery path (Phase 2) can re-queue.
                tlog.warning("task_cancelled_mid_run")
                raise
            except Exception as exc:
                task.transition_to(TaskStatus.FAILED, error=str(exc))
                tlog.exception("task_failed")

            if on_finished is not None:
                maybe = on_finished(task)
                if maybe is not None:
                    await maybe
    except asyncio.CancelledError:
        wlog.info("worker_cancelled")
        raise

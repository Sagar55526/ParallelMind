import asyncio
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any

from parallelmind.executors.base import AsyncTaskExecutor, SyncTaskExecutor
from parallelmind.models import Task


class Backend:
    """How an async worker invokes an executor.

    Three concrete impls below — see docs/concepts/04-gil-threads-processes.md.
    """

    async def run(self, executor, task: Task) -> Any:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class AsyncBackend(Backend):
    """For AsyncTaskExecutor — runs directly in the event loop."""

    async def run(self, executor: AsyncTaskExecutor, task: Task) -> Any:
        return await executor.execute(task)


class ThreadBackend(Backend):
    """For SyncTaskExecutor doing blocking IO. Each call hops onto a thread
    so the event loop keeps running. NOTE: GIL still applies — does NOT
    parallelise CPU-bound Python.
    """

    def __init__(self, max_workers: int = 8) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pm-thr")

    async def run(self, executor: SyncTaskExecutor, task: Task) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, executor.execute, task)

    async def close(self) -> None:
        self._pool.shutdown(wait=False)


class ProcessBackend(Backend):
    """For SyncTaskExecutor doing CPU-bound work. Real parallelism, but pays
    pickling + IPC cost. Executor and Task must be picklable.
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._pool = ProcessPoolExecutor(max_workers=max_workers)

    async def run(self, executor: SyncTaskExecutor, task: Task) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, executor.execute, task)

    async def close(self) -> None:
        self._pool.shutdown(wait=False)

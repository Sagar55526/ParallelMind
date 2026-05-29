import asyncio

import pytest

from parallelmind.executors.backends import AsyncBackend, ProcessBackend, ThreadBackend
from parallelmind.executors.base import AsyncTaskExecutor, SyncTaskExecutor
from parallelmind.executors.cpu_bound import PrimeCountExecutor
from parallelmind.models import Task, TaskKind


class _AsyncEcho(AsyncTaskExecutor):
    async def execute(self, task):
        await asyncio.sleep(0)
        return {"echo": task.payload.get("msg", "")}


class _SyncEcho(SyncTaskExecutor):
    def execute(self, task):
        return {"echo": task.payload.get("msg", "")}


# Module-level on purpose: ProcessBackend requires the executor class to be
# importable in the child. A class defined inside the test function would
# fail to pickle. See docs/concepts/04-gil-threads-processes.md §8.
class _Boom(SyncTaskExecutor):
    def execute(self, task):
        raise RuntimeError("nope")


async def test_async_backend_runs_async_executor():
    backend = AsyncBackend()
    out = await backend.run(_AsyncEcho(), Task(payload={"msg": "hi"}))
    assert out == {"echo": "hi"}


async def test_thread_backend_runs_sync_executor_without_blocking_loop():
    backend = ThreadBackend(max_workers=2)
    try:
        # While the thread sleeps, the event loop must still be live for other coros.
        progress = []

        async def ticker():
            for _ in range(5):
                progress.append(1)
                await asyncio.sleep(0.01)

        ticker_task = asyncio.create_task(ticker())
        out = await backend.run(_SyncEcho(), Task(payload={"msg": "ok"}))
        await ticker_task
        assert out == {"echo": "ok"}
        assert len(progress) == 5  # ticker kept running while sync work happened
    finally:
        await backend.close()


async def test_process_backend_actually_runs_cpu_task():
    backend = ProcessBackend(max_workers=2)
    try:
        task = Task(kind=TaskKind.CPU_BOUND, payload={"n": 2_000})
        out = await backend.run(PrimeCountExecutor(), task)
        assert out["primes_up_to"] == 2_000
        # Real check: primes below 2000 = 303 (well-known number)
        assert out["count"] == 303
    finally:
        await backend.close()


async def test_process_backend_propagates_exceptions():
    backend = ProcessBackend(max_workers=1)
    try:
        with pytest.raises(RuntimeError, match="nope"):
            await backend.run(_Boom(), Task())
    finally:
        await backend.close()

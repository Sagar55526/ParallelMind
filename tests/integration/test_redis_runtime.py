import asyncio
import os
import uuid

import pytest

from parallelmind.dispatcher import Dispatcher
from parallelmind.executors.base import ExecutorRegistry
from parallelmind.executors.simulated import SimulatedIOExecutor
from parallelmind.models import Task, TaskKind, TaskStatus
from parallelmind.queue.redis_queue import RedisTaskQueue

pytestmark = pytest.mark.integration


REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _unique_queue_name():
    return f"parallelmind:test:{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def queue():
    q = RedisTaskQueue.from_url(REDIS_URL, _unique_queue_name())
    await q.clear()
    yield q
    await q.clear()
    await q.close()


async def test_put_get_roundtrip_via_redis(queue):
    t = Task(kind=TaskKind.IO_SIMULATED, payload={"duration_ms": 1})
    await queue.put(t)
    assert await queue.size() == 1
    out = await queue.get(timeout=1.0)
    assert out.id == t.id


async def test_dispatcher_processes_many_tasks(queue):
    registry = ExecutorRegistry()
    registry.register(TaskKind.IO_SIMULATED, SimulatedIOExecutor())

    finished: list[Task] = []
    finished_evt = asyncio.Event()
    target = 50

    async def on_finished(task):
        finished.append(task)
        if len(finished) >= target:
            finished_evt.set()

    dispatcher = Dispatcher(queue, registry, worker_count=10, on_finished=on_finished, poll_timeout=0.2)
    await dispatcher.start()
    try:
        for _ in range(target):
            await queue.put(Task(kind=TaskKind.IO_SIMULATED, payload={"duration_ms": 5}))

        await asyncio.wait_for(finished_evt.wait(), timeout=10.0)
    finally:
        await dispatcher.stop()

    assert len(finished) == target
    assert all(t.status == TaskStatus.SUCCESS for t in finished)
    assert all(t.attempts == 1 for t in finished)


async def test_failed_executor_records_failure(queue):
    registry = ExecutorRegistry()
    registry.register(TaskKind.IO_SIMULATED, SimulatedIOExecutor())

    seen: list[Task] = []
    done = asyncio.Event()

    async def on_finished(task):
        seen.append(task)
        done.set()

    dispatcher = Dispatcher(queue, registry, worker_count=2, on_finished=on_finished, poll_timeout=0.2)
    await dispatcher.start()
    try:
        await queue.put(Task(kind=TaskKind.IO_SIMULATED, payload={"duration_ms": 1, "fail_probability": 1.0}))
        await asyncio.wait_for(done.wait(), timeout=5.0)
    finally:
        await dispatcher.stop()

    assert len(seen) == 1
    t = seen[0]
    assert t.status == TaskStatus.FAILED
    assert t.last_error is not None
    assert "simulated failure" in t.last_error

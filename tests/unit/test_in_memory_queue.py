import asyncio

import pytest

from parallelmind.models import Task, TaskStatus
from parallelmind.queue.base import QueueEmpty, QueueFull
from parallelmind.queue.in_memory import InMemoryTaskQueue


async def test_put_get_roundtrip():
    q = InMemoryTaskQueue()
    t = Task()
    await q.put(t)
    assert await q.size() == 1
    out = await q.get(timeout=0.1)
    assert out.id == t.id
    assert await q.size() == 0


async def test_get_on_empty_times_out():
    q = InMemoryTaskQueue()
    with pytest.raises(QueueEmpty):
        await q.get(timeout=0.05)


async def test_get_blocks_until_put():
    q = InMemoryTaskQueue()
    t = Task()

    async def delayed_put():
        await asyncio.sleep(0.02)
        await q.put(t)

    producer = asyncio.create_task(delayed_put())
    out = await q.get(timeout=1.0)
    await producer
    assert out.id == t.id


async def test_bounded_queue_raises_when_full():
    q = InMemoryTaskQueue(maxsize=1)
    await q.put(Task())
    with pytest.raises(QueueFull):
        await q.put(Task())


async def test_fifo_order():
    q = InMemoryTaskQueue()
    tasks = [Task() for _ in range(5)]
    for t in tasks:
        await q.put(t)
    out = [await q.get(timeout=0.1) for _ in range(5)]
    assert [t.id for t in out] == [t.id for t in tasks]


async def test_close_then_put_fails():
    q = InMemoryTaskQueue()
    await q.close()
    with pytest.raises(RuntimeError):
        await q.put(Task())


async def test_close_is_idempotent():
    q = InMemoryTaskQueue()
    await q.close()
    await q.close()


async def test_put_transitions_task_to_queued():
    q = InMemoryTaskQueue()
    t = Task()
    assert t.status == TaskStatus.CREATED
    await q.put(t)
    out = await q.get(timeout=0.1)
    assert out.status == TaskStatus.QUEUED


async def test_put_is_idempotent_on_already_queued_task():
    q = InMemoryTaskQueue()
    t = Task()
    await q.put(t)
    out = await q.get(timeout=0.1)
    await q.put(out)


async def test_concurrent_consumers_each_get_distinct_tasks():
    q = InMemoryTaskQueue()
    tasks = [Task() for _ in range(20)]
    for t in tasks:
        await q.put(t)

    async def consume():
        out = []
        try:
            while True:
                out.append(await q.get(timeout=0.05))
        except QueueEmpty:
            return out

    results = await asyncio.gather(*(consume() for _ in range(4)))
    seen_ids = [t.id for batch in results for t in batch]
    assert sorted(seen_ids) == sorted(t.id for t in tasks)
    assert len(seen_ids) == len(set(seen_ids))

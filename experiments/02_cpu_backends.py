"""Run the SAME CPU-bound task through Async / Thread / Process backends.

This is the experiment that makes the GIL visceral.

    python experiments/02_cpu_backends.py
    python experiments/02_cpu_backends.py --tasks 50 --n 50000 --process-workers 8

What to observe:
    - AsyncBackend: blocks the loop during each task -> tasks run serially
    - ThreadBackend: loop stays responsive BUT no speed-up (GIL serialises CPU)
    - ProcessBackend: real parallelism, throughput ~= min(pool_size, n_cores)
"""
import argparse
import asyncio
import os
import time

from parallelmind.executors.backends import AsyncBackend, ProcessBackend, ThreadBackend
from parallelmind.executors.base import AsyncTaskExecutor
from parallelmind.executors.cpu_bound import PrimeCountExecutor
from parallelmind.models import Task, TaskKind
from parallelmind.observability.logging import configure_logging

configure_logging(level="WARNING")


class _AsyncPrimeCount(AsyncTaskExecutor):
    """AsyncBackend needs an async executor. Wraps the sync CPU work directly —
    deliberately blocking the loop so we can SEE the cost."""

    def __init__(self):
        self._sync = PrimeCountExecutor()

    async def execute(self, task):
        return self._sync.execute(task)


async def _run_through(backend, executor, num_tasks: int, n: int) -> float:
    tasks = [Task(kind=TaskKind.CPU_BOUND, payload={"n": n}) for _ in range(num_tasks)]
    start = time.perf_counter()
    # Schedule them all concurrently — backend decides what concurrent means.
    await asyncio.gather(*(backend.run(executor, t) for t in tasks))
    return time.perf_counter() - start


def _row(label, wall, num_tasks, ideal_serial):
    per_task = wall / num_tasks
    speedup = ideal_serial / wall
    print(f"{label:<20} | {wall:>8.2f} | {per_task:>10.3f} | {speedup:>7.2f}x")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=20)
    parser.add_argument("--n", type=int, default=30_000, help="prime sieve upper bound")
    parser.add_argument("--thread-workers", type=int, default=4)
    parser.add_argument("--process-workers", type=int, default=4)
    args = parser.parse_args()

    cores = os.cpu_count() or 1
    print(
        f"\nExperiment 02: CPU-bound task through 3 backends\n"
        f"  tasks={args.tasks}  n={args.n}  cores_available={cores}\n"
        f"  thread_pool={args.thread_workers}  process_pool={args.process_workers}\n"
    )

    # Warm-up + serial baseline (one task in-process, no backend)
    sync_exec = PrimeCountExecutor()
    t0 = time.perf_counter()
    sync_exec.execute(Task(payload={"n": args.n}))
    per_serial = time.perf_counter() - t0
    ideal_serial = per_serial * args.tasks
    print(f"  per-task baseline (serial in main thread) = {per_serial*1000:.1f}ms")
    print(f"  ideal serial total = {ideal_serial:.2f}s\n")

    print(f"{'backend':<20} | {'wall(s)':>8} | {'per-task':>10} | {'speedup':>7}")
    print("-" * 60)

    async_backend = AsyncBackend()
    async_wall = await _run_through(async_backend, _AsyncPrimeCount(), args.tasks, args.n)
    _row("async (loop blocked)", async_wall, args.tasks, ideal_serial)

    thread_backend = ThreadBackend(max_workers=args.thread_workers)
    try:
        thread_wall = await _run_through(thread_backend, sync_exec, args.tasks, args.n)
        _row(f"thread (pool={args.thread_workers})", thread_wall, args.tasks, ideal_serial)
    finally:
        await thread_backend.close()

    process_backend = ProcessBackend(max_workers=args.process_workers)
    try:
        process_wall = await _run_through(process_backend, sync_exec, args.tasks, args.n)
        _row(f"process (pool={args.process_workers})", process_wall, args.tasks, ideal_serial)
    finally:
        await process_backend.close()

    print()


if __name__ == "__main__":
    asyncio.run(main())

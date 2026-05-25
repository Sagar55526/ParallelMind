"""Sweep worker count and measure throughput on an IO-bound workload.

Usage:
    python experiments/01_async_throughput.py
    python experiments/01_async_throughput.py --tasks 2000 --duration-ms 100 --workers 1,5,10,50,100,500

What to observe:
    - Throughput climbs ~linearly with worker count while we're IO-bound (waiting on asyncio.sleep)
    - Throughput plateaus once Redis round-trip / pool contention dominates
    - The KNEE of that curve is where adding workers stops paying for itself
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
import uuid

from parallelmind.dispatcher import Dispatcher
from parallelmind.executors.base import ExecutorRegistry
from parallelmind.executors.simulated import SimulatedIOExecutor
from parallelmind.models import Task, TaskKind
from parallelmind.observability.logging import configure_logging
from parallelmind.queue.redis_queue import RedisTaskQueue

configure_logging(level="WARNING")  # silence per-task INFO logs

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


async def run_one(num_tasks: int, duration_ms: int, worker_count: int) -> dict:
    queue_name = f"parallelmind:exp:{uuid.uuid4().hex[:8]}"
    # Connection pool must be >= worker_count or workers will block on each other.
    queue = RedisTaskQueue.from_url(REDIS_URL, queue_name, max_connections=worker_count + 8)

    registry = ExecutorRegistry()
    registry.register(TaskKind.IO_SIMULATED, SimulatedIOExecutor())

    finished = 0
    done_evt = asyncio.Event()
    completion_times: list[float] = []
    start: float = 0.0

    def on_finished(_task: Task) -> None:
        nonlocal finished
        finished += 1
        completion_times.append(time.perf_counter() - start)
        if finished >= num_tasks:
            done_evt.set()

    dispatcher = Dispatcher(
        queue, registry, worker_count=worker_count, on_finished=on_finished, poll_timeout=0.2
    )

    # Pre-load the queue so workers start with a full backlog (steady-state measurement).
    for _ in range(num_tasks):
        await queue.put(Task(kind=TaskKind.IO_SIMULATED, payload={"duration_ms": duration_ms}))

    start = time.perf_counter()
    await dispatcher.start()
    try:
        await asyncio.wait_for(done_evt.wait(), timeout=300.0)
    finally:
        wall_clock = time.perf_counter() - start
        await dispatcher.stop()
        await queue.clear()
        await queue.close()

    throughput = num_tasks / wall_clock
    ideal = num_tasks * (duration_ms / 1000) / worker_count
    efficiency = (ideal / wall_clock) * 100

    return {
        "workers": worker_count,
        "wall_clock_s": wall_clock,
        "throughput_tps": throughput,
        "ideal_wall_clock_s": ideal,
        "efficiency_pct": efficiency,
        "p50_completion_s": statistics.median(completion_times),
        "p95_completion_s": statistics.quantiles(completion_times, n=20)[18]
            if len(completion_times) >= 20 else completion_times[-1],
    }


def _parse_workers(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _print_row(r: dict) -> None:
    print(
        f"{r['workers']:>7} | "
        f"{r['wall_clock_s']:>10.3f} | "
        f"{r['throughput_tps']:>10.1f} | "
        f"{r['ideal_wall_clock_s']:>9.3f} | "
        f"{r['efficiency_pct']:>7.1f}% | "
        f"{r['p50_completion_s']:>7.3f} | "
        f"{r['p95_completion_s']:>7.3f}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=1000)
    parser.add_argument("--duration-ms", type=int, default=50)
    parser.add_argument("--workers", type=_parse_workers, default=[1, 10, 50, 100, 250, 500])
    args = parser.parse_args()

    print(
        f"\nExperiment 01: Async throughput sweep\n"
        f"  tasks={args.tasks}  duration_ms={args.duration_ms}  "
        f"workers={args.workers}\n"
        f"  ideal serial time = {args.tasks * args.duration_ms / 1000:.1f}s\n"
    )
    print(f"{'workers':>7} | {'wall(s)':>10} | {'tps':>10} | {'ideal(s)':>9} | {'eff':>8} | {'p50(s)':>7} | {'p95(s)':>7}")
    print("-" * 80)

    for w in args.workers:
        r = await run_one(args.tasks, args.duration_ms, w)
        _print_row(r)

    print()


if __name__ == "__main__":
    asyncio.run(main())

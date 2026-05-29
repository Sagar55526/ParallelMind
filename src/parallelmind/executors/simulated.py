import asyncio
import random
from typing import Any

from parallelmind.executors.base import AsyncTaskExecutor, ExecutorError
from parallelmind.models import Task


class SimulatedIOExecutor(AsyncTaskExecutor):
    """Sleeps for payload['duration_ms'] (default 50ms) to mimic an IO-bound call."""

    async def execute(self, task: Task) -> Any:
        duration_ms = int(task.payload.get("duration_ms", 50))
        fail_p = float(task.payload.get("fail_probability", 0.0))

        await asyncio.sleep(duration_ms / 1000)

        if fail_p > 0 and random.random() < fail_p:
            raise ExecutorError(f"simulated failure (p={fail_p})")

        return {"slept_ms": duration_ms}

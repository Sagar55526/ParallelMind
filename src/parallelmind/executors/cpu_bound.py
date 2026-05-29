from typing import Any

from parallelmind.executors.base import SyncTaskExecutor
from parallelmind.models import Task


def _count_primes_up_to(n: int) -> int:
    count = 0
    for i in range(2, n + 1):
        is_prime = True
        for j in range(2, int(i ** 0.5) + 1):
            if i % j == 0:
                is_prime = False
                break
        if is_prime:
            count += 1
    return count


class PrimeCountExecutor(SyncTaskExecutor):
    """Pure-Python prime sieve up to payload['n']. CPU-bound: holds the GIL throughout."""

    def execute(self, task: Task) -> Any:
        n = int(task.payload.get("n", 20_000))
        return {"primes_up_to": n, "count": _count_primes_up_to(n)}

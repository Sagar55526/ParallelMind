# Concept Brief #4 — The GIL, Threads, and Processes

> **Why this comes now:** Phase 1 was async-only. That's perfect for IO-bound work, but the moment a task does *real CPU work* the event loop chokes — every other worker waits. This brief explains exactly why, and what to do about it. Phase 3 wires the answers into the runtime.

---

## 1. The one-line problem

> **CPython's Global Interpreter Lock (GIL) lets only ONE thread execute Python bytecode at a time, even on a 16-core machine.**

So spawning threads to make Python "go faster" works for some workloads and is pointless for others. The two workloads behave very differently.

---

## 2. What the GIL actually is

The GIL is a mutex inside the CPython interpreter. Every Python thread that wants to execute bytecode must hold it. Only one thread holds it at a time.

```
Thread A: holds GIL ──► runs bytecode ──► releases GIL after N bytecodes (~5ms)
Thread B:                     │              ──► acquires GIL ──► runs bytecode ──► ...
Thread C:                     │              (waiting)         │
```

So with 3 threads on a CPU-bound task, you don't get 3× throughput. You get ~1× plus context-switching overhead.

**Why it exists:** CPython's memory management (reference counting) is not thread-safe. The GIL is a coarse lock that makes the whole interpreter safe without sprinkling fine-grained locks everywhere. It's been removed in Python 3.13's experimental "no-GIL" build, but the stable interpreter still has it.

---

## 3. The two workloads behave completely differently

| Workload | Time spent in… | GIL held during the slow part? |
|----------|----------------|--------------------------------|
| **IO-bound** (HTTP call, DB query, file read) | Waiting on syscalls | **NO** — the OS-level syscall releases the GIL |
| **CPU-bound** (hashing, parsing, matrix multiply) | Running Python bytecode | **YES** — the whole computation holds it |

This is the entire decision rule:

- **IO-bound + sync library** → use **threads**. Threads release the GIL during the blocking syscall, so 10 threads can wait on 10 HTTP responses in parallel.
- **IO-bound + async library** → use **asyncio** (Phase 1). Lighter than threads, same effect.
- **CPU-bound** → use **processes**. Each process has its own GIL.

---

## 4. Why `asyncio` doesn't help CPU work

A CPU-bound function blocks the event loop. There's no `await` point inside `[i**2 for i in range(10_000_000)]`, so the coroutine never yields. Every other coroutine in that loop waits.

```python
async def bad():
    return sum(i*i for i in range(10_000_000))   # 1s of CPU, NO await
```

You can wrap it in `asyncio.to_thread` to push it onto a thread — but if it's CPU work, threads can't run it in parallel either (GIL). All `to_thread` buys you is "stops blocking the event loop"; it does NOT make the work faster.

```python
result = await asyncio.to_thread(cpu_work)   # event loop OK, but cpu_work still single-cored
```

For real parallelism on CPU work, you need processes.

---

## 5. Threads vs Processes — the cost model

|                          | Thread             | Process              |
|--------------------------|--------------------|----------------------|
| Memory                   | Shared             | Separate             |
| Creation cost            | ~50 µs             | ~10–50 ms (spawn)    |
| Communication            | Shared memory      | IPC (pickle + pipe)  |
| GIL escape               | ❌                  | ✅                    |
| Crash isolation          | One bad thread = whole process dies | One bad process = others fine |
| Available data structures | All in-memory     | Must be picklable    |

Threads are cheap but single-cored. Processes are expensive but truly parallel.

**Two practical knock-on effects:**

1. **Pickling**: arguments and return values cross the process boundary as bytes. If you `submit(some_method, big_dataframe)`, that DataFrame is serialized, sent over a pipe, deserialized in the child. For tiny tasks the pickling cost can exceed the work itself.

2. **Spawn vs fork**: macOS and Python 3.14+ default to **spawn** — the child re-imports your script. If your module has top-level side effects (opening DB connections, registering routes), they run *again* in every child. Keep top-level clean.

---

## 6. `concurrent.futures` is your friend

Both pools have the same API:

```python
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

with ThreadPoolExecutor(max_workers=8) as pool:
    future = pool.submit(some_sync_function, arg1, arg2)
    result = future.result()                 # blocks

# Same shape, different pool:
with ProcessPoolExecutor(max_workers=4) as pool:
    ...
```

In `asyncio`, you don't `.result()` (it'd block the loop). You ask the loop to do it for you:

```python
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(pool, some_sync_function, arg1)
```

`run_in_executor` returns an awaitable — the loop is free to run other coroutines until the pool finishes. This is the bridge between async-land and blocking-land.

---

## 7. How this maps to ParallelMind Phase 3

We're keeping a **single async worker loop** (Phase 1's design). But the executor for each `TaskKind` now goes through a **backend** that decides how to actually invoke it:

```
Worker (async)
   │
   ▼  backend.run(executor, task)
   │
   ├── AsyncBackend       → await executor.execute(task)            ── IO-bound async tasks
   ├── ThreadBackend      → loop.run_in_executor(thread_pool, ...)  ── IO-bound sync tasks
   └── ProcessBackend     → loop.run_in_executor(process_pool, ...) ── CPU-bound tasks
```

- **`AsyncBackend`** — what Phase 1 already does.
- **`ThreadBackend`** — wraps a sync executor with `asyncio.to_thread` (uses the default thread pool, or a dedicated one). For sync DB drivers, `requests`, blocking file IO.
- **`ProcessBackend`** — wraps a sync executor with `ProcessPoolExecutor`. For CPU-bound work that needs real cores.

The registry now stores `(executor, backend)` per `TaskKind`. The worker doesn't change its loop — only how it calls the executor.

**Trade-off we're surfacing in the experiment:**
- A CPU task in `AsyncBackend` will *block other workers* (they share the loop).
- A CPU task in `ThreadBackend` will *not block the loop*, but won't be any faster than 1 core (GIL).
- A CPU task in `ProcessBackend` will be `min(N_cores, pool_size)`× faster — minus the pickling tax.

---

## 8. Footguns

1. **Process pool functions must be picklable.** Top-level functions ✅. Closures, lambdas, bound methods on non-importable classes ❌.
2. **Process pools can't share Python objects.** No shared dicts, no shared locks. Use `multiprocessing.Manager` or queues — but that's IPC-on-IPC, often slower than just doing serial work.
3. **Process pool startup is slow on macOS/Windows.** Pre-warm at app startup; don't create a fresh pool per task.
4. **Don't `to_thread` a CPU task to "fix" event-loop blocking.** It moves the problem from "blocking" to "still single-cored, just out of sight." Use a process pool.
5. **Thread pools cap at one core for Python work.** If you see CPU at 100% on one core while 15 are idle, you forgot you're CPU-bound. Switch to processes.

---

## 9. The mental decision tree

```
Is the task CPU-bound?
├── Yes → ProcessBackend
└── No  → Is the library async-native?
          ├── Yes → AsyncBackend
          └── No  → ThreadBackend
```

That's it. Three choices, one tree. Phase 3 wires it; the experiment makes it visceral.

---

## 10. What we'll see in the experiment

```bash
python experiments/02_cpu_backends.py
```

A pure-Python prime counter, ~200ms of work per task, 100 tasks:

| backend | wall (s) | per-task (s) | notes |
|---------|---------:|-------------:|-------|
| async (loop blocked!)  | ~21 | 0.21 | event loop frozen during each task |
| thread (4-thread pool) | ~21 | 0.21 | event loop OK, **but no speed-up** — GIL |
| process (4-proc pool)  | ~5.5 | 0.21 | ~4× speed-up, minus pickling overhead |

That row is the single most important thing this phase teaches: threads don't help CPU work in CPython, no matter how many you throw at it.

Now to wire it.

# Concept Brief #1 — The Event Loop & asyncio

> **Why this comes first:** ParallelMind's Phase 1 worker is `async`. If you don't have a sharp mental model of the event loop, every later decision (when to use threads vs async, why `time.sleep` is fatal, why one slow JSON parse can starve 1000 connections) will feel arbitrary.

---

## 1. The one-line definition

> **The event loop is a single thread that runs one piece of code at a time, but pauses code that's waiting on I/O and runs something else while that I/O is in flight.**

That's it. Everything else (`async def`, `await`, `Task`, `gather`) is syntax and plumbing around that idea.

---

## 2. Concurrency vs parallelism (the distinction matters here)

|                | Parallel? | Single thread? |
|----------------|-----------|----------------|
| **asyncio**    | No        | Yes            |
| **threading**  | No (in CPython, due to GIL) | No |
| **multiprocessing** | Yes  | No             |

- **Concurrency** = lots of work *in progress*. Tasks interleave.
- **Parallelism** = lots of work *executing at the same instant*. Needs multiple cores actually running code.

asyncio gives you concurrency *without* parallelism. A 1000-task asyncio program still uses one CPU core. It's just that those 1000 tasks spend 99% of their time *waiting* (for a socket, a DB response, a sleep), so the one core handles them all easily.

---

## 3. What `async def` actually creates

```python
async def fetch():
    return 42

result = fetch()        # this does NOT run fetch()!
print(type(result))     # <class 'coroutine'>
```

`async def` defines a **coroutine function**. Calling it returns a **coroutine object** — a paused, suspendable piece of computation. Nothing runs until you either `await` it or hand it to the event loop via `asyncio.run`, `asyncio.create_task`, etc.

**Mental model:** a coroutine is a generator with a state machine. Each `await` is a yield point where the function can pause.

---

## 4. What `await` does

```python
async def main():
    data = await fetch_user(42)
    print(data)
```

When the event loop encounters `await fetch_user(42)`:

1. It calls `fetch_user(42)`, which returns a coroutine (or awaitable).
2. The current function (`main`) **pauses** at the `await`. Its state (local variables, where it was) is saved.
3. The event loop is free to go run something else.
4. When `fetch_user`'s I/O completes, the loop **resumes** `main` from exactly where it paused, with `data` bound to the result.

**Key insight:** the pause is cooperative. Nothing forces a coroutine to yield. If your coroutine never `await`s, it hogs the loop. This is the #1 way to break an asyncio program.

---

## 5. The cardinal sin: blocking the event loop

```python
async def bad():
    time.sleep(2)   # BLOCKS the entire loop — every other task waits 2s
    return "done"

async def good():
    await asyncio.sleep(2)   # tells the loop "wake me in 2s", loop runs other tasks meanwhile
```

If your event loop runs on one thread and you call `time.sleep(2)`, **nothing else runs for 2 seconds**. Not your HTTP handlers, not your queue consumers, nothing.

The same applies to:
- `requests.get(...)` → use `httpx.AsyncClient` or `aiohttp`
- `psycopg2` sync queries → use `asyncpg` or async SQLAlchemy
- A CPU-heavy loop (parsing a 100MB JSON, regex on a huge string) → offload to a thread (`asyncio.to_thread`) or process pool

**Rule of thumb:** if a function takes more than ~10ms of pure CPU and you're inside `async def`, it doesn't belong on the event loop.

---

## 6. The event loop's core loop (simplified)

The actual CPython implementation lives in `asyncio/base_events.py`. The essence:

```python
while True:
    # 1. Run callbacks scheduled for "now"
    run_ready_callbacks()

    # 2. Figure out how long until the next timer fires
    timeout = compute_next_timer()

    # 3. Ask the OS: "any of these sockets ready yet? Block for at most `timeout`."
    events = selector.select(timeout)   # epoll/kqueue/IOCP under the hood

    # 4. For each socket that's ready, schedule its callback
    for event in events:
        schedule(event.callback)
```

The magic is in step 3: `selector.select` is a single OS-level syscall (`epoll_wait` on Linux, `kqueue` on macOS) that says "wake me when **any** of these N sockets has data." That's how one thread monitors thousands of connections without polling — the OS notifies us.

---

## 7. The GIL and why it doesn't bite async (much)

The Global Interpreter Lock prevents two Python threads from executing bytecode simultaneously. In async code, you only have **one thread**, so there's no contention — the GIL is held continuously by that thread. It only matters when:

- You add threads (`asyncio.to_thread`, `ThreadPoolExecutor`) — then GIL governs how they interleave.
- You're CPU-bound — then no amount of async hides that one core is saturated. (Phase 3 territory.)

For Phase 1's IO-bound workload, the GIL is a non-issue.

---

## 8. `Task` vs coroutine

```python
coro = fetch()                  # paused, not running
task = asyncio.create_task(coro)  # scheduled — loop will run it ASAP
result = await task             # wait for it to finish
```

A `Task` is a coroutine **wrapped and registered with the event loop**. Once you create a task, it starts making progress on its own; you don't have to await it immediately. This is how you get N things running concurrently:

```python
tasks = [asyncio.create_task(worker(i)) for i in range(10)]
await asyncio.gather(*tasks)    # wait for all to finish
```

Inside a single thread, those 10 workers will interleave at every `await` point.

---

## 9. How this maps to ParallelMind Phase 1

We're going to run **N async workers** (default 10) in a single event loop. Each worker:

1. `await queue.pop()` — blocks (cooperatively) until a task is available
2. Updates Postgres: `RUNNING`
3. `await execute(task)` — simulates an IO-bound workload (`asyncio.sleep`)
4. Updates Postgres: `SUCCESS` / `FAILED`
5. Loops back to step 1

While worker #3 is awaiting its DB write, workers #1, #2, #4..#10 are all making progress. **One thread, ten concurrent workers, zero locks needed** (because no two coroutines can ever run *at the same instant* — they only interleave at `await` points, which means we don't have the classic race-condition surface that threads have).

**The big learning we'll feel in the experiment:** going from 1 → 10 → 100 → 1000 workers, throughput climbs steeply at first (because we were idle waiting on I/O), then plateaus once we hit some bottleneck (Redis round-trip, Postgres connection pool, the network). Finding that knee is the whole point.

---

## 10. Common myths

| Myth | Reality |
|------|---------|
| "async is faster than sync" | Only for I/O-bound work. For CPU work, async is *slower* (overhead). |
| "async means multi-threaded" | No. One thread by default. |
| "await means wait" | It means "yield control back to the loop until this is done." If the thing is already done, no actual pause. |
| "asyncio bypasses the GIL" | No — but there's only one thread holding it, so contention is zero. |

---

## 11. Going deeper (optional reading)

- David Beazley, *Generators: The Final Frontier* — the original async-from-generators talk
- CPython source: `Lib/asyncio/base_events.py` — surprisingly readable
- `python -m asyncio` — REPL with a running loop, great for poking at this

Next up: **Task model + state machine**, then we'll wire it through the queue and worker.

# Concept Brief #2 — Redis as a Queue

> **Why this matters:** the in-memory queue from §3 worked, but it's bound to one process. The moment you have two worker processes — or you want tasks to survive a restart — you need an external broker. Redis is the simplest one that's still production-grade.

---

## 1. Why Redis (and not just a Python `Queue`)

| Property | `asyncio.Queue` | Redis |
|----------|-----------------|-------|
| Multi-process safe | ❌ | ✅ |
| Multi-host safe   | ❌ | ✅ |
| Survives process restart | ❌ | ✅ (with AOF / RDB) |
| Latency (local) | ~µs | ~100µs |
| Throughput (single key) | millions/s | ~100k ops/s |
| Built-in blocking pop | ✅ | ✅ |

The latency hit (~100µs per op) is the price of crossing a process boundary. For AI workloads where each task does ~100ms of work, that's noise.

---

## 2. The data structure: Redis LIST

Redis LISTs are doubly-linked lists. We use two operations:

- `LPUSH queue task` — push onto the **left** (head)
- `BRPOP queue timeout` — pop from the **right** (tail), **blocking**

Push left, pop right ⇒ FIFO. (You could also LPUSH/RPOP — same effect, just mirror.)

```
producer:  LPUSH q "task3"  LPUSH q "task2"  LPUSH q "task1"
           ┌──────┐ ┌──────┐ ┌──────┐
queue ──►  │task3 │→│task2 │→│task1 │
           └──────┘ └──────┘ └──────┘
                                 ▲
                                 │  BRPOP q  → "task1"   (oldest first ⇒ FIFO)
                                 │  BRPOP q  → "task2"
                                 │  BRPOP q  → "task3"
                              consumer
```

---

## 3. `BRPOP` — the magic ingredient

`BRPOP key timeout` does **blocking right-pop**:

- If the list has an element, return it immediately.
- If empty, the **connection** sleeps until either a producer LPUSHes or the timeout elapses.
- The sleep is server-side. No client polling. No CPU waste.

This is exactly the same semantic as `asyncio.Queue.get()` — except the wait happens over a socket. Internally, Redis uses an OS-level wait queue per key; when an `LPUSH` arrives, Redis wakes one blocked consumer (FIFO order among blocked consumers).

**The atomicity guarantee** (critical):
> When N consumers are blocked on `BRPOP q`, and one item is `LPUSH`ed, **exactly one consumer** gets it. No locks needed in your code.

That's why we can run 100 workers all calling `BRPOP` on the same queue and never accidentally double-process a task.

---

## 4. How `redis.asyncio` integrates with the event loop

The `redis-py` async client (`redis.asyncio`) does **not** block the event loop while waiting for `BRPOP`. Here's the chain:

1. Your worker calls `await redis.brpop(queue, timeout=5)`.
2. The client sends the `BRPOP` command bytes on the TCP socket (non-blocking write).
3. The client registers the socket with the event loop's selector (`epoll`/`kqueue`).
4. **Your worker coroutine suspends**, yielding to the event loop.
5. The event loop runs every other worker / handler in the program.
6. When Redis sends bytes back, the OS marks the socket readable, the selector returns, the loop resumes your coroutine, and `await` returns the popped value.

Net effect: 100 workers all blocked on `BRPOP` cost ~100 sockets and ~0 CPU. Same as 100 in-memory queue waiters — just with an extra hop through the kernel.

---

## 5. The big footgun: what if the worker crashes mid-task?

`BRPOP` removes the task from the queue atomically. If your worker crashes after popping but before finishing — **the task is gone**. Redis doesn't know it was unprocessed.

Two fixes:

1. **`BRPOPLPUSH`** (or `BLMOVE` in Redis 6+): atomically pop from one list and push to a "processing" list. On success, you `LREM` it from processing. On crash recovery, you scan the processing list and re-enqueue stragglers.
2. **External durable store**: write `RUNNING` to Postgres before doing work; on recovery, scan for orphaned `RUNNING` rows.

**Phase 1: we accept the crash window.** Phase 2 (retries + DLQ) introduces a processing list and reaper.

---

## 6. What we're NOT using (and why)

- **Pub/Sub**: fire-and-forget, no queueing semantics. If no consumer is listening at publish time, the message is gone. Wrong tool for tasks.
- **Streams (`XADD`/`XREAD`)**: more powerful (consumer groups, replay, persistence) but more API surface. Lists are enough for Phase 1; we'll consider Streams in Phase 6 (distributed workers).
- **SET operations**: useful for deduplication (idempotency keys) — Phase 2.

---

## 7. Connection lifecycle

A single `redis.asyncio.Redis` client maintains a connection **pool** under the hood. Each `await client.brpop(...)` checks out a connection, runs the command, returns the connection. This means:

- N workers do NOT need N separate Redis clients. One shared client is enough.
- But: while a worker is blocked on `BRPOP`, it holds a connection. So your pool size must be ≥ worker count. If you have 100 workers and a default pool of 10, 90 of them will hang waiting for a connection.

We'll size the pool to `worker_count + small headroom` in the runtime.

---

## 8. Performance numbers worth remembering

- Local Redis round-trip: **~100 µs**.
- Throughput limit for a single LIST (single-threaded Redis): **~80–100k ops/s**.
- If you saturate that, your bottleneck is Redis, not your workers — and you'd shard the queue or move to Redis Streams with consumer groups.

For Phase 1 we're nowhere near that limit. The point is to *measure* and *feel* the curve.

---

## 9. What this looks like in our code

```python
# producer
await redis.lpush(queue_name, task.to_json())

# consumer (one worker)
while True:
    result = await redis.brpop(queue_name, timeout=5)
    if result is None:
        continue            # timed out, loop and BRPOP again
    _key, raw = result
    task = Task.from_json(raw)
    await executor.execute(task)
```

That's the whole queue contract. Three lines of Redis ops. The rest is process management.

Next up: implementing it, then wiring N workers behind a single dispatcher.

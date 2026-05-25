# Concept Brief #3 — Async SQLAlchemy & FastAPI Lifespan

> **Why this comes now:** Redis holds *what's happening right now*. Postgres holds *what ever existed*. Wiring a durable store to an event-loop runtime is where most async beginners crash — sync DB libraries silently block the loop, transactions cross await points, sessions leak across requests. This brief is the safe path.

---

## 1. The two-tier state model (recap from brief #2)

| Tier | What lives there | Backend | Lifetime |
|------|------------------|---------|----------|
| Hot  | Queue, in-flight task, live counters | Redis | Seconds–minutes |
| Cold | Every task that ever existed, final status, logs | Postgres | Forever (with retention) |

The flow:

```
POST /tasks  ──► Postgres INSERT (status=CREATED)
             ──► Redis LPUSH      (status=QUEUED)
                                     │
                                     ▼  worker BRPOP
                                  RUNNING
                                     │
                                     ▼  executor.execute
                              SUCCESS/FAILED  ──► Postgres UPDATE
```

Postgres is the source of truth for "did this task ever exist and what's its current status." Redis is just the work-in-flight buffer.

---

## 2. Async SQLAlchemy in one diagram

```
                  ┌───────────────────────────────────┐
                  │  create_async_engine(url, pool_*) │   ← one per app
                  └───────────────┬───────────────────┘
                                  │
                                  ▼
                  ┌───────────────────────────────────┐
                  │  async_sessionmaker(engine)       │   ← one per app
                  └───────────────┬───────────────────┘
                                  │
                                  ▼ (per request / per unit of work)
                  ┌───────────────────────────────────┐
                  │  AsyncSession                     │   ← short-lived
                  │    .add(), .execute(), .commit()  │
                  └───────────────────────────────────┘
```

- **Engine**: a connection pool + dialect. Create ONCE at app startup. Closing it on shutdown releases all pooled connections.
- **Sessionmaker**: a factory bound to the engine. Configures session behavior (autoflush, expire-on-commit).
- **AsyncSession**: a unit-of-work. Holds an open connection, accumulates changes, commits in one shot. **Short-lived** — one per HTTP request, or per worker iteration. Never share across requests.

The driver: we use `asyncpg` (the fastest async Postgres driver). The URL `postgresql+asyncpg://...` tells SQLAlchemy to use it.

---

## 3. The single biggest async-DB gotcha

```python
# WRONG — sync driver inside async code
import psycopg2
async def get_user(id):
    conn = psycopg2.connect(...)
    cur = conn.cursor()
    cur.execute("SELECT ...")          # BLOCKS the event loop
    return cur.fetchone()
```

`psycopg2.execute` does a blocking socket read. Your one event-loop thread sits there. While it waits, **every other request, every worker, every BRPOP is frozen.**

Fix: use an async driver (`asyncpg`) end-to-end. SQLAlchemy's async API enforces this — `await session.execute(stmt)` cannot accidentally use a sync driver.

---

## 4. Transactions across `await` — the subtle rule

```python
async with session.begin():       # opens transaction
    user = await session.get(User, 1)
    user.email = "x@y"
    await some_other_thing()      # <-- another await INSIDE the transaction
    # commit happens on context exit
```

This is fine *if* `some_other_thing` doesn't itself need a DB connection from the same pool — otherwise you can deadlock (your transaction holds connection A; it awaits something that wants connection B, but the pool is exhausted).

**Rule of thumb:** keep DB transactions short. Don't `await` external IO (Redis, HTTP) while holding an open transaction. Commit first, then do the side effect, then update again if needed.

---

## 5. FastAPI lifespan — the modern startup/shutdown

Old FastAPI used `@app.on_event("startup")` decorators. Deprecated. The current way:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    engine = create_async_engine(...)
    redis = Redis.from_url(...)
    dispatcher = Dispatcher(...)
    await dispatcher.start()

    app.state.engine = engine
    app.state.redis = redis
    app.state.dispatcher = dispatcher

    yield                          # app runs here

    # SHUTDOWN
    await dispatcher.stop()
    await redis.aclose()
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
```

The `yield` is the boundary. Code before runs at startup, code after runs at shutdown. Resources go on `app.state`, retrieved by route handlers via Dependency Injection.

---

## 6. Dependency Injection — why route handlers don't `import` engines

A naive route handler:

```python
@app.post("/tasks")
async def create(req):
    engine = get_global_engine()              # tight coupling
    async with AsyncSession(engine) as s: ...
```

The FastAPI way:

```python
async def get_session(request: Request) -> AsyncSession:
    sm = request.app.state.sessionmaker
    async with sm() as session:
        yield session

@app.post("/tasks")
async def create(req, session: AsyncSession = Depends(get_session)):
    ...
```

Why bother?
- **Testability**: in tests, override `get_session` to use a transactional fixture that rolls back.
- **Scope safety**: the `yield` in `get_session` runs cleanup (close session) after the route returns, even on exception. No leaked connections.
- **One source of truth**: the route declares "I need a session," doesn't care how it's built.

---

## 7. Pydantic v2 in FastAPI — `BaseModel` vs `BaseModel` (yes, two of them)

We have two Pydantic models for Task:

1. **Domain model** (`parallelmind.models.Task`): the runtime object workers operate on. Knows about state transitions.
2. **API schemas** (`parallelmind.api.schemas.*`): the request/response shapes. Don't expose internal fields (e.g. `last_error` might be omitted from CREATE response).

This separation is standard: don't let HTTP contracts and domain logic share a class, or evolving one breaks the other.

---

## 8. Schema migrations — Alembic vs `metadata.create_all`

**Phase 1**: we use `metadata.create_all(engine)` on lifespan startup. Creates tables if missing. Good enough for a single-table schema that's still in flux.

**Phase 2+**: we'll add Alembic. The trigger is the moment we have to *change* a table without losing data (e.g. adding a `retry_after` column to the existing tasks table).

Don't add migration infrastructure before you have a migration to perform. It's overhead with no payoff yet.

---

## 9. The persistence callback — wiring it without coupling

Workers should NOT know about Postgres. The dispatcher has a `on_finished: Callable[[Task], ...]` hook. The runtime sets that hook to "write to TaskRepo." This way:

- Tests can inject a no-op hook.
- We could swap Postgres for MongoDB without touching `async_worker.py`.
- The worker remains a pure "get → execute → emit" loop.

---

## 10. What you'll see at the end of this brief

```bash
$ curl -X POST http://localhost:8000/tasks \
       -H 'Content-Type: application/json' \
       -d '{"kind": "io_simulated", "payload": {"duration_ms": 100}}'
{"id": "..." , "status": "QUEUED", ...}

$ curl http://localhost:8000/tasks/<id>
{"id": "...", "status": "SUCCESS", "attempts": 1, ...}
```

End-to-end: API submits, worker processes, Postgres records. That's the closing loop of Phase 1.

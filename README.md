# ParallelMind

> A high-throughput concurrent task execution runtime for AI workloads.

ParallelMind is a learning-driven, production-inspired execution engine — conceptually a simplified hybrid of Temporal, Celery, and Ray, focused on the concurrency primitives that make real AI infrastructure work.

---

## Architecture (Phase 1)

```
       POST /tasks                                   GET /tasks/{id}
            │                                              │
            ▼                                              ▼
       ┌──────────────────────  FastAPI app  ──────────────────────┐
       │                                                            │
       │   ┌────────────┐                       ┌─────────────────┐ │
       │   │ TaskRepo   │ ─── insert/upsert ──► │   Postgres      │ │
       │   └────────────┘                       │   (durable)     │ │
       │         │                              └─────────────────┘ │
       │         │ persist BEFORE enqueue                  ▲        │
       │         ▼                                         │        │
       │   ┌────────────┐    LPUSH    ┌─────────┐          │        │
       │   │ Queue.put  │ ──────────► │  Redis  │          │        │
       │   └────────────┘             │  LIST   │          │        │
       │                              └────┬────┘          │        │
       │                                   │ BRPOP         │        │
       │                                   ▼               │        │
       │            ┌───────────────────────────────────┐  │        │
       │            │   Dispatcher → N async workers    │  │        │
       │            │   (configurable, default 10)      │  │        │
       │            └─────────────────┬─────────────────┘  │        │
       │                              │                    │        │
       │                              ▼                    │        │
       │            ┌───────────────────────────────────┐  │        │
       │            │  ExecutorRegistry → execute()     │  │        │
       │            └─────────────────┬─────────────────┘  │        │
       │                              │                    │        │
       │                              ▼ on_finished hook   │        │
       │                            (upsert) ──────────────┘        │
       │                                                            │
       └────────────────────────────────────────────────────────────┘
```

**Key design choices** (full reasoning in [`docs/concepts/`](docs/concepts/)):

- **Two-tier state**: Redis is the *hot* queue, Postgres is the *durable* record. POST persists CREATED, enqueues (→ QUEUED), persists again. On crash the task is recoverable.
- **State machine**: every `Task` transition (`CREATED → QUEUED → RUNNING → SUCCESS/FAILED`) is validated. Illegal transitions raise immediately — bugs surface at the source, not 200 lines later.
- **Pluggable executors**: `TaskExecutor` is a Protocol, registered per `TaskKind`. Swap implementations without touching the worker loop.
- **Cooperative async pool**: N coroutines share one event loop. Cancellation-safe shutdown; in-flight tasks left in `RUNNING` for Phase 2's reaper.

---

## Tech stack

| Component       | Tool                       |
|-----------------|----------------------------|
| API             | FastAPI + uvicorn          |
| Queue / live state | Redis (LPUSH/BRPOP)     |
| Durable storage | PostgreSQL + async SQLAlchemy 2.0 (asyncpg driver) |
| Async runtime   | asyncio                    |
| Logging         | structlog (JSON)           |
| Tests           | pytest + pytest-asyncio + httpx |

---

## Local setup

Requirements: **Python 3.12+**, Docker Desktop.

```bash
# 1. Venv + install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Bring up Redis + Postgres
docker compose up -d
docker compose ps    # both must be healthy

# 3. Config
cp .env.example .env
```

> **Note on ports.** ParallelMind's Postgres is published on **5434** (not 5432) to avoid conflicts with a system Postgres. The example uvicorn command uses **8765** for the same reason. Adjust if you have nothing on those ports.

### Run tests

```bash
pytest -m "not integration"   # unit only (~0.2s)
pytest                        # full suite incl. Redis + Postgres (~1.3s)
```

### Run the API

```bash
uvicorn parallelmind.api.app:app --host 127.0.0.1 --port 8765
```

Then in another shell:

```bash
# Health
curl http://127.0.0.1:8765/healthz
# {"status":"ok"}

# Submit a task
curl -X POST http://127.0.0.1:8765/tasks \
     -H 'Content-Type: application/json' \
     -d '{"kind": "io_simulated", "payload": {"duration_ms": 50}}'
# {"id":"...", "status":"QUEUED", ...}

# Fetch its final state (worker picks it up within ms)
curl http://127.0.0.1:8765/tasks/<id>
# {"id":"...", "status":"SUCCESS", "attempts":1, ...}

# List recent
curl 'http://127.0.0.1:8765/tasks?limit=10'
```

---

## Throughput experiment

```bash
python experiments/01_async_throughput.py
python experiments/01_async_throughput.py --duration-ms 200 --workers 1,10,100,500
```

Sample results (50ms tasks, local Redis):

| workers | wall (s) | throughput (tps) | efficiency |
|---------|---------:|-----------------:|-----------:|
| 1       | 52.2     | 19               | 96%        |
| 10      | 5.4      | 187              | 93%        |
| 100     | 0.60     | 1659             | 83%        |
| 250     | 0.35     | 2862             | 57% (knee) |
| 500     | 0.37     | 2700             | 27%        |

---

## Project layout

```
src/parallelmind/
├── api/                     FastAPI app, routes, schemas, DI
├── config.py                pydantic-settings env loader
├── dispatcher.py            owns N workers; start / stop lifecycle
├── executors/               TaskExecutor protocol + registry
├── models/                  Task domain model + state machine
├── observability/logging.py structlog JSON setup
├── queue/                   in-memory + Redis-backed queues
├── storage/                 async engine, ORM TaskRow, TaskRepo
└── workers/                 run_worker coroutine loop

tests/{unit,integration}/    31 tests, ~1.3s
experiments/                 throughput sweeps
docs/concepts/               concept briefs
```

---

## Why this exists

Two goals, equally weighted:

1. **Engineer** a scalable concurrent runtime for AI workloads.
2. **Understand** what's actually happening under the hood — the GIL, the event loop, lock contention, backpressure, scheduling, the cost of process boundaries.

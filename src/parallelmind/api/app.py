from contextlib import asynccontextmanager

from fastapi import FastAPI

from parallelmind.api.routes import tasks as tasks_routes
from parallelmind.config import get_settings
from parallelmind.dispatcher import Dispatcher
from parallelmind.executors.backends import AsyncBackend, ProcessBackend, ThreadBackend
from parallelmind.executors.cpu_bound import PrimeCountExecutor
from parallelmind.executors.registry import ExecutorRegistry
from parallelmind.executors.simulated import SimulatedIOExecutor
from parallelmind.models import TaskKind
from parallelmind.observability.logging import configure_logging, get_logger
from parallelmind.queue.redis_queue import RedisTaskQueue
from parallelmind.storage.db import make_engine, make_sessionmaker
from parallelmind.storage.models import Base
from parallelmind.storage.task_repo import TaskRepo

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(level=settings.log_level)

    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    queue = RedisTaskQueue.from_url(
        settings.redis_url,
        settings.queue_name,
        max_connections=settings.async_worker_count + 8,
    )

    # Phase 3: each TaskKind is wired to a (executor, backend) pair.
    # See docs/concepts/04-gil-threads-processes.md for the decision tree.
    registry = ExecutorRegistry()
    async_backend = AsyncBackend()
    process_backend = ProcessBackend(max_workers=4)

    sim = SimulatedIOExecutor()
    registry.register(TaskKind.IO_SIMULATED, sim, async_backend)
    registry.register(TaskKind.LLM_CALL, sim, async_backend)
    registry.register(TaskKind.TOOL_CALL, sim, async_backend)
    registry.register(TaskKind.CPU_BOUND, PrimeCountExecutor(), process_backend)

    async def persist_on_finished(task):
        async with sessionmaker() as session:
            await TaskRepo(session).upsert(task)

    dispatcher = Dispatcher(
        queue,
        registry,
        worker_count=settings.async_worker_count,
        on_finished=persist_on_finished,
        poll_timeout=1.0,
    )

    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.queue = queue
    app.state.dispatcher = dispatcher
    app.state.registry = registry

    await dispatcher.start()
    log.info("app_started", workers=settings.async_worker_count)

    try:
        yield
    finally:
        log.info("app_shutting_down")
        await dispatcher.stop()
        for backend in registry.backends():
            await backend.close()
        await queue.close()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="ParallelMind", version="0.1.0", lifespan=lifespan)
    app.include_router(tasks_routes.router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


app = create_app()

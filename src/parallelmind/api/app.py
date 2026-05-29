from contextlib import asynccontextmanager

from fastapi import FastAPI

from parallelmind.api.routes import tasks as tasks_routes
from parallelmind.config import get_settings
from parallelmind.dispatcher import Dispatcher
from parallelmind.executors.base import ExecutorRegistry
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

    # Create tables if they don't exist. Phase 1 only; Phase 2 will use Alembic.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    queue = RedisTaskQueue.from_url(
        settings.redis_url,
        settings.queue_name,
        max_connections=settings.async_worker_count + 8,
    )

    registry = ExecutorRegistry()
    sim = SimulatedIOExecutor()
    registry.register(TaskKind.IO_SIMULATED, sim)
    registry.register(TaskKind.LLM_CALL, sim)
    registry.register(TaskKind.TOOL_CALL, sim)

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

    await dispatcher.start()
    log.info("app_started", workers=settings.async_worker_count)

    try:
        yield
    finally:
        log.info("app_shutting_down")
        await dispatcher.stop()
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

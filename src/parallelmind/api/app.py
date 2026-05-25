from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from parallelmind.api.routes import tasks as tasks_routes
from parallelmind.config import get_settings
from parallelmind.dispatcher import Dispatcher
from parallelmind.executors.base import ExecutorRegistry
from parallelmind.executors.simulated import SimulatedIOExecutor
from parallelmind.models import Task, TaskKind
from parallelmind.observability.logging import configure_logging, get_logger
from parallelmind.queue.redis_queue import RedisTaskQueue
from parallelmind.storage.db import make_engine, make_sessionmaker
from parallelmind.storage.models import Base
from parallelmind.storage.task_repo import TaskRepo

log = get_logger(__name__)


def _make_persistence_hook(sessionmaker: async_sessionmaker):
    """Returns an on_finished hook that upserts task state to Postgres."""

    async def _hook(task: Task) -> None:
        async with sessionmaker() as session:
            await TaskRepo(session).upsert(task)

    def hook(task: Task) -> asyncio.Future[None]:
        return asyncio.ensure_future(_hook(task))

    return hook


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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

    registry = ExecutorRegistry()
    registry.register(TaskKind.IO_SIMULATED, SimulatedIOExecutor())
    registry.register(TaskKind.LLM_CALL, SimulatedIOExecutor())
    registry.register(TaskKind.TOOL_CALL, SimulatedIOExecutor())

    dispatcher = Dispatcher(
        queue,
        registry,
        worker_count=settings.async_worker_count,
        on_finished=_make_persistence_hook(sessionmaker),
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
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from parallelmind.queue.redis_queue import RedisTaskQueue
from parallelmind.storage.task_repo import TaskRepo


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


async def get_repo(request: Request) -> AsyncIterator[TaskRepo]:
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield TaskRepo(session)


def get_queue(request: Request) -> RedisTaskQueue:
    return request.app.state.queue

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from parallelmind.models import Task
from parallelmind.storage.models import TaskRow


class TaskNotFound(Exception):
    pass


class TaskRepo:
    """Async CRUD for Task rows. One repo per session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, task: Task) -> None:
        self._session.add(TaskRow.from_domain(task))
        await self._session.commit()

    async def get(self, task_id: UUID) -> Task:
        row = await self._session.get(TaskRow, task_id)
        if row is None:
            raise TaskNotFound(str(task_id))
        return row.to_domain()

    async def upsert(self, task: Task) -> None:
        row = await self._session.get(TaskRow, task.id)
        if row is None:
            self._session.add(TaskRow.from_domain(task))
        else:
            row.status = task.status.value
            row.payload = task.payload
            row.priority = task.priority
            row.attempts = task.attempts
            row.last_error = task.last_error
            row.updated_at = task.updated_at
            row.started_at = task.started_at
            row.finished_at = task.finished_at
        await self._session.commit()

    async def list_recent(self, limit: int = 50) -> list[Task]:
        stmt = select(TaskRow).order_by(TaskRow.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return [row.to_domain() for row in result.scalars()]

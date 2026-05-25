from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from parallelmind.models import Task, TaskKind, TaskStatus


class CreateTaskRequest(BaseModel):
    kind: TaskKind = TaskKind.IO_SIMULATED
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    max_attempts: int = Field(default=3, ge=1)


class TaskResponse(BaseModel):
    id: UUID
    kind: TaskKind
    payload: dict[str, Any]
    status: TaskStatus
    priority: int
    max_attempts: int
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_domain(cls, t: Task) -> TaskResponse:
        return cls(**t.model_dump())

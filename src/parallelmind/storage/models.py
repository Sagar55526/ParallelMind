from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from parallelmind.models import Task as TaskModel, TaskKind, TaskStatus


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    priority: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=3, nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @classmethod
    def from_domain(cls, t: TaskModel) -> TaskRow:
        return cls(
            id=t.id,
            kind=t.kind.value,
            payload=t.payload,
            status=t.status.value,
            priority=t.priority,
            max_attempts=t.max_attempts,
            attempts=t.attempts,
            last_error=t.last_error,
            created_at=t.created_at,
            updated_at=t.updated_at,
            started_at=t.started_at,
            finished_at=t.finished_at,
        )

    def to_domain(self) -> TaskModel:
        return TaskModel(
            id=self.id,
            kind=TaskKind(self.kind),
            payload=self.payload or {},
            status=TaskStatus(self.status),
            priority=self.priority,
            max_attempts=self.max_attempts,
            attempts=self.attempts,
            last_error=self.last_error,
            created_at=self.created_at,
            updated_at=self.updated_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )

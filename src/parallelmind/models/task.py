from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from parallelmind.models.enums import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    TaskKind,
    TaskStatus,
)


class IllegalTransitionError(ValueError):
    def __init__(self, src: TaskStatus, dst: TaskStatus) -> None:
        super().__init__(f"Illegal transition: {src} -> {dst}")
        self.src = src
        self.dst = dst


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    kind: TaskKind = TaskKind.IO_SIMULATED
    payload: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.CREATED

    priority: int = 0
    max_attempts: int = Field(default=3, ge=1)
    attempts: int = 0
    last_error: str | None = None

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def transition_to(self, dst: TaskStatus, error: str | None = None) -> None:
        if dst not in ALLOWED_TRANSITIONS[self.status]:
            raise IllegalTransitionError(self.status, dst)

        now = _utcnow()
        self.status = dst
        self.updated_at = now

        if dst == TaskStatus.RUNNING:
            self.started_at = now
            self.attempts += 1

        if dst in TERMINAL_STATES:
            self.finished_at = now

        if error is not None:
            self.last_error = error

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> "Task":
        return cls.model_validate_json(raw)

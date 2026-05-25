"""Task — the unit of work flowing through ParallelMind.

Design choices:
  - Pydantic v2 model: validates on construction, easy JSON serialization
    (we'll need this for Redis and for the API).
  - `transition_to` is the ONLY way to mutate `status`. Direct assignment
    would bypass validation. We could enforce this with frozen=True + a
    `model_copy` pattern, but a method is more ergonomic and the project
    convention is "go through the method".
  - We carry an `attempts` counter and `last_error` from day one so Phase 2's
    retry logic doesn't require a schema migration.
"""

from __future__ import annotations

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
    """Raised when code attempts a state transition not in ALLOWED_TRANSITIONS.

    Why its own type? So callers (retry logic, dispatcher) can `except` it
    without catching unrelated ValueErrors.
    """

    def __init__(self, src: TaskStatus, dst: TaskStatus) -> None:
        super().__init__(f"Illegal transition: {src} → {dst}")
        self.src = src
        self.dst = dst


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Task(BaseModel):
    """A single unit of work, validated and serializable."""

    id: UUID = Field(default_factory=uuid4)
    kind: TaskKind = TaskKind.IO_SIMULATED
    payload: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.CREATED

    priority: int = Field(default=0, description="Higher = sooner. Reserved for Phase 2.")
    max_attempts: int = Field(default=3, ge=1)
    attempts: int = 0
    last_error: str | None = None

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def transition_to(self, dst: TaskStatus, *, error: str | None = None) -> None:
        """Move the task to `dst`. Raises IllegalTransitionError on invalid moves.

        Side effects (only on success):
          - status set to dst
          - updated_at set to now
          - started_at set when entering RUNNING
          - finished_at set when entering a terminal state
          - last_error set when error provided
          - attempts incremented when entering RUNNING
        """
        if dst not in ALLOWED_TRANSITIONS[self.status]:
            raise IllegalTransitionError(self.status, dst)

        now = _utcnow()
        self.status = dst
        self.updated_at = now

        if dst is TaskStatus.RUNNING:
            self.started_at = now
            self.attempts += 1

        if dst in TERMINAL_STATES:
            self.finished_at = now

        if error is not None:
            self.last_error = error

    # ------------------------------------------------------------------
    # Serialization helpers (queue / API need these)
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> Task:
        return cls.model_validate_json(raw)

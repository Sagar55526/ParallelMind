"""Enums for the task lifecycle.

Why a frozenset of allowed transitions instead of if/elif chains?
- Declarative: the legal graph is data, not control flow. Easier to read,
  diagram, and unit-test.
- Cheap O(1) membership checks.
- A single source of truth — the dispatcher, the worker, the API, and the
  tests all consult the same table.
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """The deterministic lifecycle of every task.

    Diagram:

        CREATED ──► QUEUED ──► RUNNING ──► SUCCESS
                                  │   └──► FAILED ──► RETRYING ──► QUEUED
                                  │                       └────► DEAD_LETTER
                                  └──► CANCELLED

    Notes:
      - RUNNING can only come from QUEUED (no resurrection from terminal states).
      - RETRYING goes back to QUEUED (retry logic is Phase 2; we'll need the
        transition wired up now so we don't redesign the state machine later).
      - SUCCESS, DEAD_LETTER, CANCELLED are *terminal*. No exits.
    """

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


# Adjacency list: state -> set of legal next states.
# Terminal states map to empty sets.
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.FAILED: frozenset({TaskStatus.RETRYING, TaskStatus.DEAD_LETTER}),
    TaskStatus.RETRYING: frozenset({TaskStatus.QUEUED}),
    TaskStatus.SUCCESS: frozenset(),
    TaskStatus.DEAD_LETTER: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


TERMINAL_STATES: frozenset[TaskStatus] = frozenset(
    state for state, nexts in ALLOWED_TRANSITIONS.items() if not nexts
)


def is_transition_allowed(src: TaskStatus, dst: TaskStatus) -> bool:
    return dst in ALLOWED_TRANSITIONS[src]


class TaskKind(StrEnum):
    """What kind of work the task represents.

    The dispatcher uses this to pick a worker pool. In Phase 1 every kind
    routes to the async pool; Phase 3 introduces thread/process routing.
    """

    IO_SIMULATED = "io_simulated"  # asyncio.sleep — for benchmarks
    LLM_CALL = "llm_call"          # external HTTP, IO-bound
    TOOL_CALL = "tool_call"        # external HTTP, IO-bound
    CPU_BOUND = "cpu_bound"        # placeholder, routed to process pool in Phase 3

from enum import Enum


class TaskStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


# state -> allowed next states. Empty set = terminal.
ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CREATED: {TaskStatus.QUEUED, TaskStatus.CANCELLED},
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.FAILED: {TaskStatus.RETRYING, TaskStatus.DEAD_LETTER},
    TaskStatus.RETRYING: {TaskStatus.QUEUED},
    TaskStatus.SUCCESS: set(),
    TaskStatus.DEAD_LETTER: set(),
    TaskStatus.CANCELLED: set(),
}

TERMINAL_STATES: set[TaskStatus] = {s for s, nexts in ALLOWED_TRANSITIONS.items() if not nexts}


class TaskKind(str, Enum):
    IO_SIMULATED = "io_simulated"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    CPU_BOUND = "cpu_bound"

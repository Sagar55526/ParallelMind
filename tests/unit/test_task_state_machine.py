import pytest

from parallelmind.models import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    IllegalTransitionError,
    Task,
    TaskStatus,
)


def test_default_task_starts_in_created():
    t = Task()
    assert t.status == TaskStatus.CREATED
    assert t.attempts == 0
    assert t.started_at is None
    assert t.finished_at is None


def test_happy_path_transitions():
    t = Task()
    t.transition_to(TaskStatus.QUEUED)
    t.transition_to(TaskStatus.RUNNING)
    t.transition_to(TaskStatus.SUCCESS)
    assert t.status == TaskStatus.SUCCESS
    assert t.attempts == 1
    assert t.started_at is not None
    assert t.finished_at is not None


def test_running_increments_attempts():
    t = Task()
    t.transition_to(TaskStatus.QUEUED)
    t.transition_to(TaskStatus.RUNNING)
    assert t.attempts == 1
    t.transition_to(TaskStatus.FAILED)
    t.transition_to(TaskStatus.RETRYING)
    t.transition_to(TaskStatus.QUEUED)
    t.transition_to(TaskStatus.RUNNING)
    assert t.attempts == 2


def test_failed_carries_error_message():
    t = Task()
    t.transition_to(TaskStatus.QUEUED)
    t.transition_to(TaskStatus.RUNNING)
    t.transition_to(TaskStatus.FAILED, error="boom")
    assert t.last_error == "boom"


def test_terminal_states_have_no_exits():
    for state in TERMINAL_STATES:
        assert ALLOWED_TRANSITIONS[state] == set()


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATES))
def test_cannot_leave_terminal_state(terminal):
    t = Task(status=terminal)
    for dst in TaskStatus:
        with pytest.raises(IllegalTransitionError):
            t.transition_to(dst)


def test_illegal_transition_raises_with_context():
    t = Task()  # CREATED
    with pytest.raises(IllegalTransitionError) as exc:
        t.transition_to(TaskStatus.RUNNING)
    assert exc.value.src == TaskStatus.CREATED
    assert exc.value.dst == TaskStatus.RUNNING


def test_serialization_roundtrip():
    t = Task()
    t.transition_to(TaskStatus.QUEUED)
    t.transition_to(TaskStatus.RUNNING)
    revived = Task.from_json(t.to_json())
    assert revived == t


def test_is_terminal_property():
    assert not Task().is_terminal
    t = Task()
    t.transition_to(TaskStatus.QUEUED)
    t.transition_to(TaskStatus.RUNNING)
    t.transition_to(TaskStatus.SUCCESS)
    assert t.is_terminal

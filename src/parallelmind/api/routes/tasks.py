from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from parallelmind.api.deps import get_queue, get_repo
from parallelmind.api.schemas import CreateTaskRequest, TaskResponse
from parallelmind.models import Task
from parallelmind.queue.redis_queue import RedisTaskQueue
from parallelmind.storage.task_repo import TaskNotFound, TaskRepo

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: CreateTaskRequest,
    repo: TaskRepo = Depends(get_repo),
    queue: RedisTaskQueue = Depends(get_queue),
) -> TaskResponse:
    task = Task(
        kind=body.kind,
        payload=body.payload,
        priority=body.priority,
        max_attempts=body.max_attempts,
    )
    # Persist first (durable record), then enqueue (hand off to runtime),
    # then persist again to reflect the QUEUED state. If the LPUSH fails,
    # the row is left as CREATED — recoverable, not lost.
    await repo.insert(task)
    await queue.put(task)  # mutates task.status -> QUEUED
    await repo.upsert(task)
    return TaskResponse.from_domain(task)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, repo: TaskRepo = Depends(get_repo)) -> TaskResponse:
    try:
        task = await repo.get(task_id)
    except TaskNotFound as e:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found") from e
    return TaskResponse.from_domain(task)


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    limit: int = 50, repo: TaskRepo = Depends(get_repo)
) -> list[TaskResponse]:
    tasks = await repo.list_recent(limit=limit)
    return [TaskResponse.from_domain(t) for t in tasks]

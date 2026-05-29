import asyncio
import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from parallelmind.api.app import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    """Each test gets a unique queue name so they don't interfere."""
    qname = f"parallelmind:test:api:{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("QUEUE_NAME", qname)
    monkeypatch.setenv("ASYNC_WORKER_COUNT", "4")


@pytest.fixture
async def app_client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            yield client


async def test_healthz(app_client):
    resp = await app_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_create_task_returns_201_and_queued_status(app_client):
    resp = await app_client.post(
        "/tasks",
        json={"kind": "io_simulated", "payload": {"duration_ms": 5}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "QUEUED"
    assert body["kind"] == "io_simulated"
    assert body["attempts"] == 0


async def test_task_runs_to_success(app_client):
    resp = await app_client.post(
        "/tasks",
        json={"kind": "io_simulated", "payload": {"duration_ms": 5}},
    )
    task_id = resp.json()["id"]

    for _ in range(50):
        await asyncio.sleep(0.1)
        r = await app_client.get(f"/tasks/{task_id}")
        if r.json()["status"] in {"SUCCESS", "FAILED"}:
            break

    final = (await app_client.get(f"/tasks/{task_id}")).json()
    assert final["status"] == "SUCCESS"
    assert final["attempts"] == 1
    assert final["started_at"] is not None
    assert final["finished_at"] is not None


async def test_get_missing_task_returns_404(app_client):
    resp = await app_client.get(f"/tasks/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_list_tasks_returns_recent(app_client):
    for _ in range(3):
        await app_client.post("/tasks", json={"kind": "io_simulated", "payload": {"duration_ms": 1}})
    resp = await app_client.get("/tasks?limit=10")
    assert resp.status_code == 200
    assert len(resp.json()) >= 3

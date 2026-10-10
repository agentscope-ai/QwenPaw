# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers import backup as backup_router
from qwenpaw.backup import manager as manager_module
from qwenpaw.backup._ops.create import BackupCancelled
from qwenpaw.backup.manager import BackupManager
from qwenpaw.backup.models import BackupJobStatus


def _payload() -> dict:
    return {
        "name": "router-test",
        "scope": {
            "include_agents": False,
            "include_global_config": False,
            "include_secrets": False,
            "include_skill_pool": False,
        },
        "agents": [],
    }


async def _wait_for_status(
    manager: BackupManager,
    job_id: str,
    status: BackupJobStatus,
):
    for _ in range(200):
        snapshot = manager.get_job(job_id)
        if snapshot and snapshot.status == status:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError(f"job did not reach {status}")


@pytest.fixture(name="backup_app")
def backup_app_fixture():
    app = FastAPI()
    app.state.backup_manager = BackupManager()
    app.state.multi_agent_manager = None
    app.include_router(backup_router.router, prefix="/api")
    return app


async def test_job_api_starts_finds_and_cancels_job(
    backup_app,
    monkeypatch,
):
    def fake_create(_meta, _agents, _progress, stop_event):
        assert stop_event.wait(timeout=2)
        raise BackupCancelled()

    monkeypatch.setattr(manager_module, "create_backup", fake_create)
    transport = ASGITransport(app=backup_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        started = await client.post("/api/backups/jobs", json=_payload())
        assert started.status_code == 202
        job_id = started.json()["job_id"]

        active = await client.get("/api/backups/jobs/active")
        assert active.status_code == 200
        assert active.json()["job_id"] == job_id

        cancelled = await client.post(f"/api/backups/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancel_requested"

    await _wait_for_status(
        backup_app.state.backup_manager,
        job_id,
        BackupJobStatus.CANCELLED,
    )


async def test_restore_is_rejected_while_create_is_running(
    backup_app,
    monkeypatch,
):
    release = threading.Event()

    def fake_create(meta, _agents, _progress, _stop_event):
        assert release.wait(timeout=2)
        return meta

    monkeypatch.setattr(manager_module, "create_backup", fake_create)
    transport = ASGITransport(app=backup_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        started = await client.post("/api/backups/jobs", json=_payload())
        job_id = started.json()["job_id"]
        response = await client.post(
            "/api/backups/existing/restore",
            json={"include_agents": False, "agent_ids": []},
        )
        assert response.status_code == 409

    release.set()
    await _wait_for_status(
        backup_app.state.backup_manager,
        job_id,
        BackupJobStatus.COMPLETED,
    )

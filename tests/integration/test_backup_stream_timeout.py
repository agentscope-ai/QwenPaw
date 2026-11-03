# -*- coding: utf-8 -*-
"""Real-TCP regression test for backup SSE idle timeouts."""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from qwenpaw.app.routers import backup as backup_router
from qwenpaw.backup import manager as manager_module
from qwenpaw.backup.manager import BackupManager
from qwenpaw.backup.models import BackupJobStatus


_CLIENT_IDLE_TIMEOUT_SECONDS = 0.2
_BACKUP_DURATION_SECONDS = 0.6


def _payload() -> dict:
    return {
        "name": "tcp-timeout-test",
        "scope": {
            "include_agents": False,
            "include_global_config": False,
            "include_secrets": False,
            "include_skill_pool": False,
        },
        "agents": [],
    }


async def _wait_for_completed(
    manager: BackupManager,
    job_id: str,
):
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        snapshot = manager.get_job(job_id)
        if snapshot and snapshot.status == BackupJobStatus.COMPLETED:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError("backup job did not complete")


@asynccontextmanager
async def _serve_over_tcp(app: FastAPI) -> AsyncIterator[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            lifespan="off",
            log_level="error",
            access_log=False,
        ),
    )
    server_task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            if server_task.done():
                await server_task
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("local uvicorn server did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await server_task
        sock.close()


@pytest.mark.integration
@pytest.mark.p1
async def test_backup_sse_idle_timeout_ab(monkeypatch):
    """A loses an idle stream; B survives it with heartbeat bytes."""
    observed_stop_events: list[threading.Event] = []

    def slow_backup(meta, _agents, _progress, stop_event):
        observed_stop_events.append(stop_event)
        time.sleep(_BACKUP_DURATION_SECONDS)
        return meta

    monkeypatch.setattr(manager_module, "create_backup", slow_backup)
    manager = BackupManager()
    app = FastAPI()
    app.state.backup_manager = manager
    app.state.multi_agent_manager = None
    app.include_router(backup_router.router, prefix="/api")
    timeout = httpx.Timeout(2.0, read=_CLIENT_IDLE_TIMEOUT_SECONDS)

    async with _serve_over_tcp(app) as base_url:
        # A: no bytes arrive before the simulated gateway idle timeout.
        monkeypatch.setattr(backup_router, "_SSE_HEARTBEAT_SECONDS", 1.0)
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            trust_env=False,
        ) as client:
            response = await client.post("/api/backups/jobs", json=_payload())
            assert response.status_code == 202
            job_a = response.json()["job_id"]

            with pytest.raises(httpx.ReadTimeout):
                async with client.stream(
                    "GET",
                    f"/api/backups/jobs/{job_a}/events",
                ) as stream:
                    assert stream.status_code == 200
                    async for _line in stream.aiter_lines():
                        pass

            completed_a = await _wait_for_completed(manager, job_a)
            queried_a = await client.get(f"/api/backups/jobs/{job_a}")
            assert queried_a.status_code == 200
            assert queried_a.json()["status"] == "completed"
            assert completed_a.status == BackupJobStatus.COMPLETED
            assert observed_stop_events[0].is_set() is False

        # B: heartbeat bytes arrive inside the same idle timeout window.
        monkeypatch.setattr(backup_router, "_SSE_HEARTBEAT_SECONDS", 0.05)
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            trust_env=False,
        ) as client:
            response = await client.post("/api/backups/jobs", json=_payload())
            assert response.status_code == 202
            job_b = response.json()["job_id"]
            heartbeat_count = 0
            terminal = None

            async with client.stream(
                "GET",
                f"/api/backups/jobs/{job_b}/events",
            ) as stream:
                assert stream.status_code == 200
                async for line in stream.aiter_lines():
                    if line == ": heartbeat":
                        heartbeat_count += 1
                    elif line.startswith("data: "):
                        snapshot = json.loads(line.removeprefix("data: "))
                        if snapshot["status"] == "completed":
                            terminal = snapshot
                            break

            assert heartbeat_count >= 2
            assert terminal is not None
            assert terminal["job_id"] == job_b
            assert observed_stop_events[1].is_set() is False

# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.routers.skills``.

Per the issue acceptance criteria the focus is on:

- ``GET /skills`` — list workspace skills
- ``GET /skills/hub/search`` — hub search wrapper
- ``GET /skills/pool`` — pool listing
- Hub install task lifecycle: start → status → cancel
- ``GET /skills/hub/install/status/{id}`` 404 for unknown task

Note: the install pipeline itself (``install_skill_from_hub``) is mocked
out — that worker has its own dedicated tests; here we only check the
router wires the lifecycle endpoints together correctly.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import skills as skills_module
from qwenpaw.app.routers.skills import router as skills_router


@pytest.fixture(autouse=True)
def _clear_install_registries():
    """Each test starts with empty install task registries."""
    skills_module._hub_install_tasks.clear()
    skills_module._hub_install_runtime_tasks.clear()
    skills_module._hub_install_cancel_events.clear()
    yield
    skills_module._hub_install_tasks.clear()
    skills_module._hub_install_runtime_tasks.clear()
    skills_module._hub_install_cancel_events.clear()


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.state.multi_agent_manager = MagicMock(name="ManagerStub")
    # ``skills_router`` already declares ``prefix="/skills"`` so we only
    # add the outer ``/api`` mount point used in production.
    application.include_router(skills_router, prefix="/api")
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_workspace(tmp_path: Path):
    workspace = MagicMock(name="Workspace")
    workspace.workspace_dir = str(tmp_path)
    workspace.agent_id = "default"
    return workspace


@pytest.fixture
def patch_get_agent(fake_workspace):
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(return_value=fake_workspace),
    ) as patched:
        yield patched


# ---------------------------------------------------------------------------
# GET /skills
# ---------------------------------------------------------------------------


def test_list_skills_returns_workspace_specs(client, patch_get_agent):
    with patch(
        "qwenpaw.app.routers.skills._build_workspace_skill_specs",
        return_value=[],
    ) as build_mock:
        response = client.get("/api/skills")

    assert response.status_code == 200
    assert response.json() == []
    build_mock.assert_called_once()


def test_list_skills_404_when_agent_lookup_fails(client):
    from fastapi import HTTPException

    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(
            side_effect=HTTPException(status_code=404, detail="missing"),
        ),
    ):
        response = client.get("/api/skills")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /skills/hub/search
# ---------------------------------------------------------------------------


def test_search_hub_returns_mapped_specs(client):
    from types import SimpleNamespace

    fake_hub_result = SimpleNamespace(
        slug="cool-skill",
        name="Cool Skill",
        description="useful",
        version="1.0",
        source_url="https://hub/cool",
        author="alice",
        icon_url="",
    )
    with patch(
        "qwenpaw.app.routers.skills.search_hub_skills",
        new=AsyncMock(return_value=[fake_hub_result]),
    ) as search_mock:
        response = client.get("/api/skills/hub/search?q=cool&limit=5")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["slug"] == "cool-skill"
    search_mock.assert_awaited_once_with("cool", limit=5)


# ---------------------------------------------------------------------------
# GET /skills/pool
# ---------------------------------------------------------------------------


def test_list_pool_skills_returns_pool_specs(client):
    with patch(
        "qwenpaw.app.routers.skills._build_pool_skill_specs",
        return_value=[],
    ) as build_mock:
        response = client.get("/api/skills/pool")

    assert response.status_code == 200
    assert response.json() == []
    build_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Hub install lifecycle
# ---------------------------------------------------------------------------


def test_start_install_registers_task_and_returns_id(
    client,
    patch_get_agent,
):
    # Replace the background worker with a no-op so the test does not
    # touch the real install pipeline.
    async def noop(*_args, **_kwargs):
        return None

    with patch(
        "qwenpaw.app.routers.skills._run_hub_install_task",
        new=noop,
    ):
        response = client.post(
            "/api/skills/hub/install/start",
            json={"bundle_url": "https://hub/example.zip"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bundle_url"] == "https://hub/example.zip"
    assert body["status"] == "pending"
    task_id = body["task_id"]
    assert task_id in skills_module._hub_install_tasks


def test_get_install_status_returns_task(client, patch_get_agent):
    async def noop(*_args, **_kwargs):
        return None

    with patch(
        "qwenpaw.app.routers.skills._run_hub_install_task",
        new=noop,
    ):
        start = client.post(
            "/api/skills/hub/install/start",
            json={"bundle_url": "https://hub/x.zip"},
        )

    task_id = start.json()["task_id"]
    status = client.get(f"/api/skills/hub/install/status/{task_id}")
    assert status.status_code == 200
    assert status.json()["task_id"] == task_id


def test_get_install_status_404_for_unknown_task(client):
    response = client.get("/api/skills/hub/install/status/no-such-task")

    assert response.status_code == 404


def test_cancel_install_marks_task_cancelled(client, patch_get_agent):
    async def noop(*_args, **_kwargs):
        # Hold open so the cancel path sees it as not-yet-complete.
        await asyncio.sleep(60)

    with patch(
        "qwenpaw.app.routers.skills._run_hub_install_task",
        new=noop,
    ):
        start = client.post(
            "/api/skills/hub/install/start",
            json={"bundle_url": "https://hub/x.zip"},
        )
        task_id = start.json()["task_id"]

        cancel = client.post(f"/api/skills/hub/install/cancel/{task_id}")

    assert cancel.status_code == 200
    assert cancel.json() == {"task_id": task_id, "status": "cancelled"}
    cancel_event = skills_module._hub_install_cancel_events[task_id]
    assert cancel_event.is_set()


def test_cancel_install_404_for_unknown_task(client):
    response = client.post("/api/skills/hub/install/cancel/no-such-task")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Validation: missing bundle_url returns 422
# ---------------------------------------------------------------------------


def test_start_install_422_on_missing_bundle_url(client, patch_get_agent):
    response = client.post(
        "/api/skills/hub/install/start",
        json={"version": "1.0"},
    )

    assert response.status_code == 422

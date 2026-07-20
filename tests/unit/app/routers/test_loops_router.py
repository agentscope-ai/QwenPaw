# -*- coding: utf-8 -*-
"""Tests for custom loop mode persistence endpoints."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.loops import router
from qwenpaw.config.config import CustomLoopModeConfig, GateInstanceConfig


def _mode(mode_id: str = "quality") -> CustomLoopModeConfig:
    return CustomLoopModeConfig(
        id=mode_id,
        name="Quality",
        slash_command=mode_id,
        enabled=True,
        gates=[
            GateInstanceConfig(
                id="limit",
                type="iteration",
                params={"max_iterations": 20},
            ),
        ],
    )


@pytest.fixture
def workspace() -> SimpleNamespace:
    registry = MagicMock()
    registry.names.return_value = []
    return SimpleNamespace(
        agent_id="default",
        config=SimpleNamespace(
            running=SimpleNamespace(
                loop=SimpleNamespace(custom_modes=[]),
            ),
        ),
        plugins=SimpleNamespace(slash_command_registry=registry),
    )


@pytest.fixture
def client(workspace: SimpleNamespace):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with (
        patch(
            "qwenpaw.app.routers.loops.get_agent_for_request",
            new=AsyncMock(return_value=workspace),
        ),
        patch("qwenpaw.app.routers.loops.save_agent_config") as save,
        patch("qwenpaw.app.routers.loops.schedule_agent_reload") as reload,
    ):
        yield TestClient(app), save, reload


def test_catalog_exposes_only_builtin_gates(client) -> None:
    test_client, _, _ = client

    response = test_client.get("/api/loops/gates/catalog")

    assert response.status_code == 200
    assert {item["type"] for item in response.json()} == {
        "iteration",
        "doom_loop",
        "token_budget",
        "timeout",
        "tool_call_budget",
        "text_response_retry",
        "completion_rubric",
    }


def test_create_custom_mode_persists_and_schedules_reload(client) -> None:
    test_client, save, reload = client

    response = test_client.post(
        "/api/loops/custom",
        json=_mode().model_dump(),
    )

    assert response.status_code == 201, response.text
    save.assert_called_once()
    reload.assert_called_once()


def test_create_rejects_unknown_gate_even_when_disabled(client) -> None:
    test_client, save, reload = client
    payload = _mode().model_dump()
    payload["enabled"] = False
    payload["gates"][0]["enabled"] = False
    payload["gates"][0]["type"] = "user_python_gate"

    response = test_client.post("/api/loops/custom", json=payload)

    assert response.status_code == 422
    assert "Unknown built-in gate type" in response.json()["detail"]
    save.assert_not_called()
    reload.assert_not_called()


def test_create_rejects_registered_command(client, workspace) -> None:
    test_client, save, _ = client
    workspace.plugins.slash_command_registry.names.return_value = ["quality"]

    response = test_client.post(
        "/api/loops/custom",
        json=_mode().model_dump(),
    )

    assert response.status_code == 409
    save.assert_not_called()


def test_create_rejects_duplicate_normalized_name(client, workspace) -> None:
    """The persistence API rejects ambiguous display names."""
    test_client, save, reload = client
    workspace.config.running.loop.custom_modes = [_mode()]
    duplicate = _mode("quality-copy")
    duplicate.name = " quality "

    response = test_client.post(
        "/api/loops/custom",
        json=duplicate.model_dump(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Mode name exists"
    save.assert_not_called()
    reload.assert_not_called()

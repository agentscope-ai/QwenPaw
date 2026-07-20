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
from qwenpaw.app.agent_context import get_current_session_id
from qwenpaw.config.config import CustomLoopModeConfig, GateInstanceConfig
from qwenpaw.modes.custom_loop.mode import (
    DeclarativeLoopMode,
    LoopModeActivationStore,
)
from qwenpaw.modes.goal.goal_mode import GoalMode, GoalSession


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
        plugins=SimpleNamespace(
            slash_command_registry=registry,
            modes=[],
        ),
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


def test_loop_catalog_includes_enabled_custom_and_plugin_modes(
    client,
    workspace,
) -> None:
    """Chat discovery is workspace-local and excludes disabled modes."""
    enabled = _mode()
    disabled = _mode("disabled")
    disabled.enabled = False
    workspace.config.running.loop.custom_modes = [enabled, disabled]

    class PluginMode:
        name = "review"

        @staticmethod
        def commands():
            from qwenpaw.runtime.slash_command_registry import CommandSpec

            async def handler(_ctx, _args):
                return None

            return [
                CommandSpec(
                    name="review",
                    handler=handler,
                    help_text="Review the current work.",
                    metadata={"loop_name": "Review"},
                ),
            ]

        @staticmethod
        def is_active(_ctx):
            return False

    workspace.plugins.modes = [PluginMode()]

    response = client[0].get("/api/loops")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [
        "default",
        "goal",
        "mission",
        "custom:quality",
        "plugin:review",
    ]
    assert response.json()[-1]["name"] == "Review"


def test_loop_status_reports_active_mode_and_restores_context(
    client,
    workspace,
) -> None:
    """Status inspection uses the requested session without leaking it."""

    class PluginMode:
        name = "review"

        @staticmethod
        def commands():
            from qwenpaw.runtime.slash_command_registry import CommandSpec

            async def handler(_ctx, _args):
                return None

            return [CommandSpec(name="review", handler=handler)]

        @staticmethod
        def is_active(ctx):
            return (
                ctx.session_id == "session-a"
                and get_current_session_id() == "session-a"
            )

    workspace.plugins.modes = [PluginMode()]

    response = client[0].get(
        "/api/loops/status",
        params={"session_id": "session-a"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "active"
    assert response.json()["mode"]["id"] == "plugin:review"
    assert get_current_session_id() is None


def test_loop_status_treats_default_as_idle(client, workspace) -> None:
    """Default is the absence of an explicit persistent mode."""

    class DefaultMode:
        name = "default"

        @staticmethod
        def is_active(_ctx):
            return True

    workspace.plugins.modes = [DefaultMode()]

    response = client[0].get(
        "/api/loops/status",
        params={"session_id": "session-a"},
    )

    assert response.status_code == 200
    assert response.json() == {"state": "idle", "mode": None}


def test_loop_status_reports_goal_for_only_its_session(
    client,
    workspace,
) -> None:
    """Goal activity remains isolated by conversation session."""
    goal_mode = GoalMode()
    goal_mode.sessions["session-a"] = GoalSession(goal="Ship it")
    workspace.plugins.modes = [goal_mode]

    active = client[0].get(
        "/api/loops/status",
        params={"session_id": "session-a"},
    )
    idle = client[0].get(
        "/api/loops/status",
        params={"session_id": "session-b"},
    )

    assert active.json()["mode"]["id"] == "goal"
    assert idle.json() == {"state": "idle", "mode": None}


def test_loop_status_reports_custom_mode(client, workspace) -> None:
    """Declarative custom activation is exposed with its original copy."""
    config = _mode()
    store = LoopModeActivationStore()
    custom_mode = DeclarativeLoopMode(config, store)
    store.activate("session-a", config.id)
    workspace.config.running.loop.custom_modes = [config]
    workspace.plugins.modes = [custom_mode]

    response = client[0].get(
        "/api/loops/status",
        params={"session_id": "session-a"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == {
        "id": "custom:quality",
        "name": "Quality",
        "slash_command": "quality",
        "description": "",
        "source": "custom",
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

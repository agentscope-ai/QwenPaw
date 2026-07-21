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
from qwenpaw.modes.mission import MissionMode


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
    assert response.json()["state"] == "awaiting_user"
    assert response.json()["mode"]["id"] == "plugin:review"
    assert get_current_session_id() is None


@pytest.mark.parametrize(
    ("run_status", "expected_state"),
    [("running", "running"), ("idle", "awaiting_user")],
)
def test_loop_status_reports_chat_execution_phase(
    client,
    workspace,
    run_status,
    expected_state,
) -> None:
    """Chat execution and persistent mode lifecycle remain distinct."""

    class PluginMode:
        name = "review"

        @staticmethod
        def commands():
            from qwenpaw.runtime.slash_command_registry import CommandSpec

            async def handler(_ctx, _args):
                return None

            return [CommandSpec(name="review", handler=handler)]

        @staticmethod
        def is_active(_ctx):
            return True

    chat = SimpleNamespace(
        id="chat-a",
        session_id="session-a",
        user_id="user-a",
        channel="console",
    )
    workspace.plugins.modes = [PluginMode()]
    workspace.chat_manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
    )
    workspace.task_tracker = SimpleNamespace(
        get_status=AsyncMock(return_value=run_status),
    )
    workspace.session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value={}),
    )

    response = client[0].get(
        "/api/loops/status",
        params={"chat_id": "chat-a"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == expected_state
    assert response.json()["mode"]["id"] == "plugin:review"


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


def test_loop_status_restores_stage_one_mission(client, workspace) -> None:
    """Persisted Mission Stage 1 remains visible after mode reload."""
    chat = SimpleNamespace(
        id="chat-a",
        session_id="session-a",
        user_id="user-a",
        channel="console",
    )
    workspace.plugins.modes = [MissionMode()]
    workspace.chat_manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
    )
    workspace.task_tracker = SimpleNamespace(
        get_status=AsyncMock(return_value="idle"),
    )
    workspace.session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={
                "agent": {
                    "mode_state": {
                        "mission": {
                            "active": True,
                            "loop_dir": "/tmp/mission-stage-one",
                            "phase": "prd_generation",
                        },
                    },
                },
            },
        ),
    )

    response = client[0].get(
        "/api/loops/status",
        params={"chat_id": "chat-a"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "awaiting_user"
    assert response.json()["mode"]["id"] == "mission"


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


def test_duplicate_custom_mode_is_available_immediately(
    client,
    workspace,
) -> None:
    """Copies with active gates remain available to the current agent."""
    workspace.config.running.loop.custom_modes = [_mode()]

    response = client[0].post("/api/loops/custom/quality/duplicate")

    assert response.status_code == 201, response.text
    assert response.json()["enabled"] is True


def test_duplicate_custom_mode_keeps_fields_within_limits(
    client,
    workspace,
) -> None:
    """Boundary-length source values produce a valid persisted copy."""
    source = CustomLoopModeConfig(
        id="a" * 64,
        name="N" * 80,
        slash_command="b" * 64,
        enabled=False,
    )
    workspace.config.running.loop.custom_modes = [source]

    response = client[0].post(
        f"/api/loops/custom/{source.id}/duplicate",
    )

    assert response.status_code == 201, response.text
    duplicate = CustomLoopModeConfig.model_validate(response.json())
    assert len(duplicate.id) <= 64
    assert len(duplicate.name) <= 80
    assert len(duplicate.slash_command) <= 64


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


def test_create_rejects_unicode_casefold_name(client, workspace) -> None:
    """Save-time uniqueness matches reload-time Unicode normalization."""
    test_client, save, reload = client
    existing = _mode()
    existing.name = "Straße"
    workspace.config.running.loop.custom_modes = [existing]
    duplicate = _mode("quality-copy")
    duplicate.name = "STRASSE"

    response = test_client.post(
        "/api/loops/custom",
        json=duplicate.model_dump(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Mode name exists"
    save.assert_not_called()
    reload.assert_not_called()

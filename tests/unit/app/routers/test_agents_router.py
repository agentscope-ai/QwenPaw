# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.routers.agents``.

Covers the 5 highest-value flows:

- ``GET /agents`` — list all agents
- ``GET /agents/{id}`` — fetch single agent, 404 on missing
- ``PUT /agents/order`` — reject duplicate or mismatched IDs (400)
- ``DELETE /agents/{id}`` — refuse to delete ``default`` (400)
- ``DELETE /agents/{id}`` — happy path with manager.stop_agent
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentscope_runtime.engine.schemas.exception import AppBaseException
from qwenpaw.app.routers.agents import router as agents_router
from qwenpaw.config.config import AgentProfileConfig, AgentProfileRef


def _ref(agent_id: str, *, enabled: bool = True) -> AgentProfileRef:
    return AgentProfileRef(
        id=agent_id,
        workspace_dir=f"/tmp/ws/{agent_id}",
        enabled=enabled,
    )


@pytest.fixture
def manager_mock():
    mgr = MagicMock(name="MultiAgentManager")
    mgr.stop_agent = AsyncMock(return_value=None)
    return mgr


@pytest.fixture
def app(manager_mock) -> FastAPI:
    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(agents_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_config():
    """A minimal load_config() return: two profiles, ``default`` + ``bot``."""
    config = MagicMock(name="AppConfig")
    config.agents = MagicMock()
    config.agents.profiles = {
        "default": _ref("default"),
        "bot": _ref("bot"),
    }
    config.agents.agent_order = ["default", "bot"]
    return config


# ---------------------------------------------------------------------------
# GET /agents
# ---------------------------------------------------------------------------


def test_list_agents_returns_all_profiles(client, fake_config):
    agent_cfg_default = AgentProfileConfig(
        id="default",
        name="Default",
        description="primary",
        workspace_dir="/tmp/ws/default",
    )
    agent_cfg_bot = AgentProfileConfig(
        id="bot",
        name="Bot",
        description="",
        workspace_dir="/tmp/ws/bot",
    )

    def fake_load(agent_id):
        return {
            "default": agent_cfg_default,
            "bot": agent_cfg_bot,
        }[agent_id]

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            side_effect=fake_load,
        ),
    ):
        response = client.get("/api/agents")

    assert response.status_code == 200
    body = response.json()
    assert {a["id"] for a in body["agents"]} == {"default", "bot"}


def test_list_agents_falls_back_to_id_when_load_fails(client, fake_config):
    # When ``load_agent_config`` raises, the handler must still surface
    # the agent with a derived name rather than 500-ing the whole list.
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            side_effect=RuntimeError("config broken"),
        ),
    ):
        response = client.get("/api/agents")

    assert response.status_code == 200
    names = {a["name"] for a in response.json()["agents"]}
    # Defaults: title-cased agent IDs.
    assert names == {"Default", "Bot"}


# ---------------------------------------------------------------------------
# GET /agents/{id}
# ---------------------------------------------------------------------------


def test_get_agent_returns_config(client):
    cfg = AgentProfileConfig(
        id="bot",
        name="Bot",
        description="",
        workspace_dir="/tmp/ws/bot",
    )

    with patch(
        "qwenpaw.app.routers.agents.load_agent_config",
        return_value=cfg,
    ):
        response = client.get("/api/agents/bot")

    assert response.status_code == 200
    assert response.json()["id"] == "bot"


def test_get_agent_returns_404_for_missing(client):
    with patch(
        "qwenpaw.app.routers.agents.load_agent_config",
        side_effect=ValueError("no such agent"),
    ):
        response = client.get("/api/agents/ghost")

    assert response.status_code == 404


def test_get_agent_returns_404_for_app_base_exception(client):
    with patch(
        "qwenpaw.app.routers.agents.load_agent_config",
        side_effect=AppBaseException(
            status=404,
            code="agent_not_found",
            message="nope",
        ),
    ):
        response = client.get("/api/agents/ghost")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /agents/order
# ---------------------------------------------------------------------------


def test_reorder_agents_rejects_duplicate_ids(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.put(
            "/api/agents/order",
            json={"agent_ids": ["default", "default"]},
        )

    assert response.status_code == 400
    assert "exactly once" in response.json()["detail"]


def test_reorder_agents_rejects_mismatched_ids(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.put(
            "/api/agents/order",
            json={"agent_ids": ["default", "ghost"]},
        )

    assert response.status_code == 400


def test_reorder_agents_happy_path_saves(client, fake_config):
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch("qwenpaw.app.routers.agents.save_config") as save_mock,
    ):
        response = client.put(
            "/api/agents/order",
            json={"agent_ids": ["bot", "default"]},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    save_mock.assert_called_once()


# ---------------------------------------------------------------------------
# DELETE /agents/{id}
# ---------------------------------------------------------------------------


def test_delete_agent_refuses_default(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.delete("/api/agents/default")

    assert response.status_code == 400
    assert "Cannot delete the default agent" in response.json()["detail"]


def test_delete_agent_404_when_missing(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.delete("/api/agents/ghost")

    assert response.status_code == 404


def test_delete_agent_happy_path_calls_stop_and_saves(
    client,
    fake_config,
    manager_mock,
):
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch("qwenpaw.app.routers.agents.save_config") as save_mock,
    ):
        response = client.delete("/api/agents/bot")

    assert response.status_code == 200
    assert response.json() == {"success": True, "agent_id": "bot"}
    manager_mock.stop_agent.assert_awaited_once_with("bot")
    save_mock.assert_called_once()
    assert "bot" not in fake_config.agents.profiles

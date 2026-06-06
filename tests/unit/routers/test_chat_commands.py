# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for the chat commands router (/chat-commands)."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers.chat_commands import router


# ---- helpers ---------------------------------------------------------


def _mock_workspace(agent_id="test_agent", chat_commands=None):
    """Build a mock workspace whose config has given chat_commands."""
    ws = MagicMock()
    ws.agent_id = agent_id
    config = MagicMock()
    config.running = MagicMock()
    config.running.chat_commands = (
        chat_commands[:]
        if chat_commands
        else ["clear", "compact", "mission", "skills"]
    )
    ws.config = config
    return ws


# ---- app fixture -----------------------------------------------------


@pytest.fixture
def app_client():
    """Create async test client with the chat-commands router mounted.

    Monkey-patches _get_workspace and save_agent_config so tests
    don't need a real config.json or agent.json on disk.
    """
    app = FastAPI()
    app.include_router(router)  # router has prefix="/chat-commands"

    # Store the last PUT value so GET round-trip works
    _stored: dict = {}

    async def _fake_get_workspace(request):
        agent_id = getattr(request.state, "agent_id", "test_agent")
        cmds = getattr(request.state, "mock_chat_commands", None)
        ws = _mock_workspace(agent_id, cmds)
        # Round-trip support: if PUT was called, reflect the updated value
        if _stored:
            ws.config.running.chat_commands = list(
                _stored.get("cmds", ws.config.running.chat_commands),
            )
        return ws

    def _fake_save_agent_config(agent_id, agent_config):
        _stored["agent_id"] = agent_id
        _stored["cmds"] = list(agent_config.running.chat_commands)

    with (
        patch(
            "qwenpaw.app.routers.chat_commands._get_workspace",
            _fake_get_workspace,
        ),
        patch(
            "qwenpaw.app.routers.chat_commands.save_agent_config",
            _fake_save_agent_config,
        ),
    ):
        transport = ASGITransport(app=app)
        yield AsyncClient(transport=transport, base_url="http://test")


# ---- 1. GET /available -------------------------------------------------


async def test_get_available_returns_all_21_commands(app_client):
    async with app_client:
        resp = await app_client.get("/chat-commands/available")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 21

    by_name = {c["command"]: c for c in data}

    assert by_name["daemon_status"]["display"] == "/status"
    assert by_name["daemon_restart"]["display"] == "/restart"
    assert by_name["daemon_logs"]["display"] == "/logs"
    assert by_name["daemon_reload_config"]["display"] == "/reload-config"
    assert by_name["daemon_reload_config_alt"]["display"] == "/reload_config"

    assert by_name["clear"]["category"] == "context"
    assert by_name["history"]["category"] == "history"
    assert by_name["model"]["category"] == "model"
    assert by_name["skills"]["category"] == "session"
    assert by_name["stop"]["category"] == "control"

    assert by_name["clear"]["has_args"] is False
    assert by_name["message"]["has_args"] is True


# ---- 2. GET / (defaults) -----------------------------------------------


async def test_get_default_commands(app_client):
    async with app_client:
        resp = await app_client.get("/chat-commands")
    assert resp.status_code == 200
    assert resp.json()["commands"] == ["clear", "compact", "mission", "skills"]


# ---- 3. PUT + GET round-trip ------------------------------------------


async def test_put_then_get(app_client):
    new_list = ["clear", "new", "history", "stop"]
    async with app_client:
        put_resp = await app_client.put(
            "/chat-commands",
            json={"commands": new_list},
        )
        get_resp = await app_client.get("/chat-commands")
    assert put_resp.status_code == 200
    assert put_resp.json()["commands"] == new_list
    assert get_resp.json()["commands"] == new_list


# ---- 4. PUT dedup -----------------------------------------------------


async def test_put_dedup_preserves_order(app_client):
    async with app_client:
        put_resp = await app_client.put(
            "/chat-commands",
            json={"commands": ["clear", "compact", "clear", "new", "compact"]},
        )
    assert put_resp.status_code == 200
    assert put_resp.json()["commands"] == ["clear", "compact", "new"]


# ---- 5. PUT filters invalid commands -----------------------------------


async def test_put_filters_invalid_commands(app_client):
    async with app_client:
        put_resp = await app_client.put(
            "/chat-commands",
            json={"commands": ["clear", "nonexistent", "compact", "fake_cmd"]},
        )
    assert put_resp.status_code == 200
    assert put_resp.json()["commands"] == ["clear", "compact"]


# ---- 6. Old agent.json fallback (defaults) -----------------------------


async def test_get_empty_list_falls_back_to_default(app_client):
    async with app_client:
        resp = await app_client.get("/chat-commands")
    assert resp.status_code == 200
    assert resp.json()["commands"] == ["clear", "compact", "mission", "skills"]

# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.routers.config``.

Scope: representative subset of the config router as called out in the
acceptance criteria — GET / PUT happy paths, 404 / 422 validation
errors.  Covers:

- ``GET /config/channels/types`` — pure list
- ``GET /config/channels`` — happy path through ``get_agent_for_request``
- ``PUT /config/channels`` — round-trip + agent reload trigger
- ``GET /config/security/tool-guard`` — happy path
- ``PUT /config/security/tool-guard`` — happy path + engine reload
- 422 on a malformed PUT body
- 404 propagated from ``get_agent_for_request``
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from qwenpaw.app.crons import heartbeat
from qwenpaw.app.routers.config import router as config_router
from qwenpaw.config.config import (
    ChannelConfig,
    ConsoleConfig,
    HeartbeatConfig,
    ToolGuardConfig,
)
from qwenpaw.constant import (
    HEARTBEAT_FILE,
    HEARTBEAT_TARGET_INBOX,
    HEARTBEAT_TARGET_LAST,
)


class _HeartbeatWorkspace:
    async def stream_query(self, _req):
        for event in ():
            yield event


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    # Manager isn't used directly by these endpoints once we patch
    # ``get_agent_for_request``, but keep state attribute populated to
    # avoid spurious 500s from the auth-context fallback.
    application.state.multi_agent_manager = MagicMock(name="ManagerStub")
    application.include_router(config_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_agent_workspace():
    """Workspace stub whose ``config`` has channels + agent_id attribute."""
    workspace = MagicMock(name="Workspace")
    workspace.agent_id = "default"
    workspace.config = MagicMock(name="AgentConfig")
    workspace.config.channels = ChannelConfig(
        console=ConsoleConfig(enabled=True),
    )
    return workspace


@pytest.fixture
def patch_get_agent(fake_agent_workspace):
    """Patch ``get_agent_for_request`` (imported lazily inside handlers)."""
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(return_value=fake_agent_workspace),
    ) as patched:
        yield patched


# ---------------------------------------------------------------------------
# /config/channels/types — pure list, no deps
# ---------------------------------------------------------------------------


def test_list_channel_types_returns_list(client):
    response = client.get("/api/config/channels/types")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    # Built-in identifiers must include 'console'.
    assert "console" in body


# ---------------------------------------------------------------------------
# /config/channels — list + put
# ---------------------------------------------------------------------------


def test_list_channels_returns_dict_with_isBuiltin_flag(
    client,
    patch_get_agent,
):
    response = client.get("/api/config/channels")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    # The 'console' built-in channel must show up.
    assert "console" in body
    assert body["console"]["isBuiltin"] is True


def test_list_channels_404_when_agent_lookup_fails(client):
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(
            side_effect=HTTPException(status_code=404, detail="nope"),
        ),
    ):
        response = client.get("/api/config/channels")

    assert response.status_code == 404


def test_put_channels_saves_and_triggers_reload(
    client,
    fake_agent_workspace,
    patch_get_agent,
):
    with (
        patch(
            "qwenpaw.config.config.save_agent_config",
        ) as save_mock,
        patch(
            "qwenpaw.app.routers.config.schedule_agent_reload",
        ) as reload_mock,
    ):
        payload = ChannelConfig(
            console=ConsoleConfig(enabled=False),
        ).model_dump()
        response = client.put("/api/config/channels", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["console"]["enabled"] is False

    # Side-effects fired exactly once.
    save_mock.assert_called_once()
    reload_mock.assert_called_once()


def test_put_channels_422_on_invalid_payload(client, patch_get_agent):
    # ``console.enabled`` must be a bool — give it a string instead so
    # Pydantic rejects the body at validation time, before our code runs.
    response = client.put(
        "/api/config/channels",
        json={"console": {"enabled": "not-a-bool-and-not-coercible"}},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /config/heartbeat — get + put
# ---------------------------------------------------------------------------


def test_get_heartbeat_returns_timeout_seconds(
    client,
    fake_agent_workspace,
    patch_get_agent,
):
    fake_agent_workspace.config.heartbeat = HeartbeatConfig(
        enabled=True,
        every="2h",
        target="inbox",
        timeoutSeconds=240,
    )

    response = client.get("/api/config/heartbeat")

    assert response.status_code == 200
    assert response.json()["timeoutSeconds"] == 240


def test_put_heartbeat_preserves_timeout_seconds(
    client,
    fake_agent_workspace,
    patch_get_agent,
):
    fake_agent_workspace.cron_manager = None

    with patch("qwenpaw.config.config.save_agent_config") as save_mock:
        response = client.put(
            "/api/config/heartbeat",
            json={
                "enabled": True,
                "every": "2h",
                "target": "inbox",
                "timeoutSeconds": 360,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timeoutSeconds"] == 360
    assert fake_agent_workspace.config.heartbeat.timeout_seconds == 360
    save_mock.assert_called_once()


def test_heartbeat_config_rejects_timeout_above_max():
    with pytest.raises(ValueError):
        HeartbeatConfig(timeoutSeconds=3601)


def test_put_heartbeat_rejects_timeout_above_max(
    client,
    fake_agent_workspace,
    patch_get_agent,
):
    fake_agent_workspace.cron_manager = None

    response = client.put(
        "/api/config/heartbeat",
        json={
            "enabled": True,
            "every": "2h",
            "target": "inbox",
            "timeoutSeconds": 3601,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "last_dispatch"),
    [
        ("main", None),
        (
            HEARTBEAT_TARGET_LAST,
            SimpleNamespace(
                channel="console",
                user_id="user-1",
                session_id="session-1",
            ),
        ),
        (HEARTBEAT_TARGET_INBOX, None),
    ],
)
async def test_run_heartbeat_once_uses_configured_timeout(
    monkeypatch,
    tmp_path,
    target,
    last_dispatch,
):
    (tmp_path / HEARTBEAT_FILE).write_text("check status", encoding="utf-8")
    seen_timeouts: list[float] = []

    async def fake_wait_for(awaitable, timeout):
        seen_timeouts.append(timeout)
        return await awaitable

    monkeypatch.setattr(heartbeat.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(
        heartbeat,
        "get_heartbeat_config",
        lambda _agent_id=None: HeartbeatConfig(
            enabled=True,
            target=target,
            timeoutSeconds=240,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(last_dispatch=last_dispatch),
    )
    monkeypatch.setattr(
        heartbeat,
        "read_session_messages",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(heartbeat, "create_trace", AsyncMock())
    monkeypatch.setattr(
        heartbeat,
        "append_trace_from_session_delta",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(heartbeat, "finalize_trace", AsyncMock())
    monkeypatch.setattr(heartbeat, "append_inbox_event", AsyncMock())

    await heartbeat.run_heartbeat_once(
        workspace=_HeartbeatWorkspace(),
        channel_manager=SimpleNamespace(send_event=AsyncMock()),
        agent_id="agent-1",
        workspace_dir=tmp_path,
    )

    assert seen_timeouts == [240]


# ---------------------------------------------------------------------------
# /config/security/tool-guard
# ---------------------------------------------------------------------------


def test_get_tool_guard_returns_current_config(client):
    fake_cfg = MagicMock()
    fake_cfg.security.tool_guard = ToolGuardConfig(enabled=True)

    with patch(
        "qwenpaw.app.routers.config.load_config",
        return_value=fake_cfg,
    ):
        response = client.get("/api/config/security/tool-guard")

    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_put_tool_guard_saves_and_reloads_engine(client):
    fake_cfg = MagicMock()
    fake_cfg.security.tool_guard = ToolGuardConfig(enabled=False)
    engine_mock = MagicMock(enabled=False)

    with (
        patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ),
        patch("qwenpaw.app.routers.config.save_config") as save_mock,
        patch(
            "qwenpaw.security.tool_guard.engine.get_guard_engine",
            return_value=engine_mock,
        ),
    ):
        response = client.put(
            "/api/config/security/tool-guard",
            json={"enabled": True},
        )

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    save_mock.assert_called_once()
    # The handler must flip the engine flag AND ask it to reload rules.
    assert engine_mock.enabled is True
    engine_mock.reload_rules.assert_called_once()

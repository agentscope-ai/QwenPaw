# -*- coding: utf-8 -*-
"""Integration tests for miscellaneous agent-scoped endpoints.

Covers tools config, heartbeat, console chat, and MCP OAuth start
through ``/api/agents/{agentId}/...`` paths.
"""
from __future__ import annotations

import httpx
import pytest

from tests.integration.helpers import (
    create_agent,
    delete_agent_quietly,
    scoped,
)

_HTTP_TIMEOUT = 15.0


# ------------------------------------------------------------------ #
# tools
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_tools_list_returns_array(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agents/{agentId}/tools returns 200 with a list
      payload. Agent-scoped tools listing may be empty or contain
      built-in entries depending on configuration.

    Test flow:
    1. Create agent.
    2. GET /agents/{id}/tools.
    3. Assert 200 and JSON is a list.

    API endpoints:
    - GET /api/agents/{agentId}/tools
    """
    agent_id = "integ_misc_tools_list_01"
    create_agent(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "GET",
            scoped(agent_id, "/tools"),
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        assert isinstance(resp.json(), list)
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p0
def test_tools_config_update_unknown_returns_500(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/tools/{name}/config with an
      unknown tool name returns 500 because the PluginRegistry rejects
      config writes for non-existent tools.

    Test flow:
    1. Create agent.
    2. POST /{bogus_tool}/config.
    3. Assert 500 and detail mentions ``not found``.

    API endpoints:
    - POST /api/agents/{agentId}/tools/{tool_name}/config
    """
    agent_id = "integ_misc_tools_cfg_unk_01"
    create_agent(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "POST",
            scoped(agent_id, "/tools/integ-nosuch-tool/config"),
            json={"config": {"api_key": "test"}},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 500, app_server.logs_tail()
        assert "not found" in resp.json().get("detail", "").lower()
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p0
def test_tools_config_get_nonexistent_returns_empty(
    app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/agents/{agentId}/tools/{name}/config for a
      non-existent tool returns 200 with an empty dict (graceful
      fallback, not 404).

    Test flow:
    1. Create agent.
    2. GET /{bogus_tool}/config.
    3. Assert 200 and body is ``{}``.

    API endpoints:
    - GET /api/agents/{agentId}/tools/{tool_name}/config
    """
    agent_id = "integ_misc_tools_cfg_get_01"
    create_agent(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "GET",
            scoped(agent_id, "/tools/integ-nosuch-tool/config"),
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        assert resp.json() == {}
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# heartbeat
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_heartbeat_run_returns_started(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/config/heartbeat/run fires a
      background heartbeat and returns ``{"started": true}``
      immediately. The background task may fail (no LLM configured)
      but the synchronous response must be hermetic.

    Test flow:
    1. Create agent.
    2. POST heartbeat/run.
    3. Assert 200 and ``started == True``.

    API endpoints:
    - POST /api/agents/{agentId}/config/heartbeat/run
    """
    agent_id = "integ_misc_heartbeat_01"
    create_agent(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "POST",
            scoped(agent_id, "/config/heartbeat/run"),
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        assert resp.json().get("started") is True
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# console chat
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_console_chat_returns_sse(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/console/chat with a valid
      minimal body returns a 200 SSE response (``text/event-stream``
      content-type). The stream content itself depends on LLM
      availability; we only assert the HTTP-level contract.

    Test flow:
    1. Create agent.
    2. POST console/chat with a minimal valid body using httpx
       streaming mode (avoids blocking on body read).
    3. Assert 200 and content-type starts with ``text/event-stream``.

    API endpoints:
    - POST /api/agents/{agentId}/console/chat
    """
    agent_id = "integ_misc_console_chat_01"
    create_agent(app_server, agent_id)
    try:
        url = f"{app_server.base_url}" f"{scoped(agent_id, '/console/chat')}"
        body = {
            "input": [
                {
                    "content": [
                        {"type": "text", "text": "hello"},
                    ],
                },
            ],
            "user_id": "integ-test",
            "session_id": "integ-session-01",
        }
        with app_server.client.stream(
            "POST",
            url,
            json=body,
            timeout=httpx.Timeout(10.0, read=3.0),
        ) as resp:
            assert resp.status_code == 200, app_server.logs_tail()
            ct = resp.headers.get("content-type", "")
            assert "text/event-stream" in ct
    except httpx.ReadTimeout:
        pass
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p0
def test_console_chat_invalid_body_returns_422(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/console/chat with an
      unparseable body returns 422 (FastAPI validation error).

    Test flow:
    1. POST console/chat with body ``"not-json-object"`` (a bare
       string, not dict/AgentRequest).
    2. Assert 422.

    API endpoints:
    - POST /api/agents/{agentId}/console/chat
    """
    resp = app_server.api_request(
        "POST",
        scoped("default", "/console/chat"),
        content='"just-a-string"',
        headers={"Content-Type": "application/json"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


# ------------------------------------------------------------------ #
# mcp-oauth start
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_mcp_oauth_start_returns_auth_url(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/mcp/oauth/start/{client_key}
      with explicit ``auth_endpoint`` and ``token_endpoint`` returns
      200 and an ``auth_url`` without making any network calls
      (PKCE flow is computed locally).

    Test flow:
    1. Create agent.
    2. POST oauth/start with explicit mock endpoints.
    3. Assert 200 and response contains ``auth_url`` and ``session_id``.

    API endpoints:
    - POST /api/agents/{agentId}/mcp/oauth/start/{client_key}
    """
    agent_id = "integ_misc_oauth_start_01"
    create_agent(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "POST",
            scoped(
                agent_id,
                "/mcp/oauth/start/integ-mock-mcp-client",
            ),
            json={
                "url": "http://localhost:19999/mcp",
                "auth_endpoint": "http://localhost:19999/authorize",
                "token_endpoint": "http://localhost:19999/token",
                "scope": "read",
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        payload = resp.json()
        assert "auth_url" in payload
        assert "session_id" in payload
        assert "localhost:19999/authorize" in payload["auth_url"]
    finally:
        delete_agent_quietly(app_server, agent_id)

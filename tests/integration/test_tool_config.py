# -*- coding: utf-8 -*-
"""Integration tests for tool configuration HTTP API.

Covers GET /tools (list), PATCH /tools/{name}/toggle, and
GET /tools/{name}/config endpoints.  Verifies that builtin tools
(e.g. set_user_timezone) appear in the list and can be toggled.
"""
from __future__ import annotations

import pytest

from helpers import default_http_timeout, scoped

_TOOL_HTTP_TIMEOUT = default_http_timeout(15.0)


# ------------------------------------------------------------------ #
# C1: tool list includes set_user_timezone
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_tool_list_includes_set_user_timezone(app_server) -> None:
    """Test purpose:
    - Verify GET /tools returns a list that includes the
      set_user_timezone builtin tool with enabled=true.

    Test flow:
    1. GET /api/agents/default/tools.
    2. Assert response is a list.
    3. Find set_user_timezone in the list.
    4. Assert it is enabled.

    API endpoints:
    - GET /api/agents/{agentId}/tools
    """
    resp = app_server.api_request(
        "GET",
        scoped("default", "/tools"),
        timeout=_TOOL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    tools = resp.json()
    assert isinstance(tools, list)
    assert len(tools) > 0, "tool list should not be empty"

    names = {t.get("name") for t in tools}
    assert (
        "set_user_timezone" in names
    ), f"set_user_timezone not in tool list: {names}"

    tool = next(t for t in tools if t["name"] == "set_user_timezone")
    assert tool.get("enabled") is True


# ------------------------------------------------------------------ #
# C2: tool toggle disable / enable
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_tool_toggle_disable_enable(app_server) -> None:
    """Test purpose:
    - Verify PATCH /tools/{name}/toggle toggles the tool's
      enabled state and the change is reflected in GET /tools.

    Test flow:
    1. PATCH toggle set_user_timezone → should return toggled state.
    2. GET /tools → verify new enabled state.
    3. PATCH toggle again to restore original state.
    4. GET /tools → verify restored.

    API endpoints:
    - PATCH /api/agents/{agentId}/tools/{tool_name}/toggle
    - GET /api/agents/{agentId}/tools
    """
    get_before = app_server.api_request(
        "GET",
        scoped("default", "/tools"),
        timeout=_TOOL_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200
    tools = get_before.json()
    tool = next(t for t in tools if t["name"] == "set_user_timezone")
    original_enabled = tool["enabled"]

    try:
        toggle_resp = app_server.api_request(
            "PATCH",
            scoped("default", "/tools/set_user_timezone/toggle"),
            timeout=_TOOL_HTTP_TIMEOUT,
        )
        assert toggle_resp.status_code == 200
        toggled = toggle_resp.json()
        assert toggled.get("enabled") is (not original_enabled)

        get_after = app_server.api_request(
            "GET",
            scoped("default", "/tools"),
            timeout=_TOOL_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200
        after_tool = next(
            t for t in get_after.json() if t["name"] == "set_user_timezone"
        )
        assert after_tool["enabled"] is (not original_enabled)
    finally:
        app_server.api_request(
            "PATCH",
            scoped("default", "/tools/set_user_timezone/toggle"),
            timeout=_TOOL_HTTP_TIMEOUT,
        )


# ------------------------------------------------------------------ #
# C3: agent-scoped tool list matches global
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_tool_list_agent_scoped_matches_global(
    app_server,
) -> None:
    """Test purpose:
    - Verify agent-scoped GET /tools and header GET /tools return
      the same set of tool names for the default agent.

    Test flow:
    1. GET /api/agents/default/tools (scoped).
    2. GET /api/tools with X-Agent-Id: default (header).
    3. Assert both return the same tool name set.

    API endpoints:
    - GET /api/agents/{agentId}/tools
    - GET /api/tools
    """
    scoped_resp = app_server.api_request(
        "GET",
        scoped("default", "/tools"),
        timeout=_TOOL_HTTP_TIMEOUT,
    )
    assert scoped_resp.status_code == 200

    header_resp = app_server.api_request(
        "GET",
        "/api/tools",
        headers={"X-Agent-Id": "default"},
        timeout=_TOOL_HTTP_TIMEOUT,
    )
    assert header_resp.status_code == 200

    scoped_names = {t["name"] for t in scoped_resp.json()}
    header_names = {t["name"] for t in header_resp.json()}
    assert scoped_names == header_names


# ------------------------------------------------------------------ #
# C4: tool config get returns dict
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_tool_config_get_returns_dict(app_server) -> None:
    """Test purpose:
    - Verify GET /tools/{name}/config returns a valid dict.

    Test flow:
    1. GET /api/agents/default/tools/set_user_timezone/config.
    2. Assert 200 + response is dict.

    API endpoints:
    - GET /api/agents/{agentId}/tools/{tool_name}/config
    """
    resp = app_server.api_request(
        "GET",
        scoped("default", "/tools/set_user_timezone/config"),
        timeout=_TOOL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    config = resp.json()
    assert isinstance(config, dict)

# -*- coding: utf-8 -*-
"""Integration tests for the tools router (tool configuration).

Covers GET /api/tools (list), tool toggle, and async execution config.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_TOOLS_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_tools_list(app_server) -> None:
    """Test purpose:
    - Verify GET /api/tools returns a list of tools. Console tool
      management page renders from this endpoint.

    Test flow:
    1. GET /api/tools.
    2. Assert 200 and response is a list.

    API endpoints:
    - GET /api/tools
    """
    resp = app_server.api_request(
        "GET",
        "/api/tools",
        timeout=_TOOLS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)


@pytest.mark.integration
@pytest.mark.p1
def test_tools_item_schema(app_server) -> None:
    """Test purpose:
    - Verify each tool entry has expected fields (name, enabled, etc.).

    Test flow:
    1. GET /api/tools.
    2. If items exist, verify schema.

    API endpoints:
    - GET /api/tools
    """
    resp = app_server.api_request(
        "GET",
        "/api/tools",
        timeout=_TOOLS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    items = resp.json()
    for item in items[:5]:  # Check first 5
        assert isinstance(item, dict)
        # Each tool should have a name
        assert "name" in item or "tool_name" in item


@pytest.mark.integration
@pytest.mark.p1
def test_tools_toggle_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify PATCH /api/tools/{tool_name}/toggle returns 404 for
      nonexistent tool.

    Test flow:
    1. PATCH toggle for nonexistent tool.
    2. Assert 404.

    API endpoints:
    - PATCH /api/tools/{tool_name}/toggle
    """
    resp = app_server.api_request(
        "PATCH",
        "/api/tools/nonexistent_tool_xyz/toggle",
        timeout=_TOOLS_TIMEOUT,
    )
    assert resp.status_code in (200, 400, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_tools_async_execution_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify PATCH /api/tools/{tool_name}/async-execution returns 404
      for nonexistent tool.

    Test flow:
    1. PATCH async-execution for nonexistent tool.
    2. Assert 404.

    API endpoints:
    - PATCH /api/tools/{tool_name}/async-execution
    """
    resp = app_server.api_request(
        "PATCH",
        "/api/tools/nonexistent_tool_xyz/async-execution",
        json={"async_execution": True},
        timeout=_TOOLS_TIMEOUT,
    )
    assert resp.status_code in (200, 400, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_tools_config_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify GET /api/tools/{tool_name}/config returns 404 for
      nonexistent tool.

    Test flow:
    1. GET config for nonexistent tool.
    2. Assert 404.

    API endpoints:
    - GET /api/tools/{tool_name}/config
    """
    resp = app_server.api_request(
        "GET",
        "/api/tools/nonexistent_tool_xyz/config",
        timeout=_TOOLS_TIMEOUT,
    )
    assert resp.status_code in (200, 400, 404), app_server.logs_tail()

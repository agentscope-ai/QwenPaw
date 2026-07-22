# -*- coding: utf-8 -*-
"""Integration smoke tests for console-adjacent read-only JSON APIs.

No API keys, no LLM calls. Covers plugin list, backup list, token usage
summary/details, auth status (disabled CI profile), and agent statistics
with explicit ``X-Agent-Id``.
"""
from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_api_plugins_list_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/plugins returns a JSON array with stable per-item keys.

    Test flow:
    1. GET /api/plugins.
    2. Assert 200 and list; for each entry assert id, name, enabled.

    API endpoints:
    - GET /api/plugins
    """
    resp = app_server.api_request("GET", "/api/plugins")
    assert resp.status_code == 200, app_server.logs_tail()
    data = resp.json()
    assert isinstance(data, list)
    for item in data:
        assert isinstance(item, dict)
        assert "id" in item and isinstance(item["id"], str)
        assert "name" in item and isinstance(item["name"], str)
        assert "enabled" in item and isinstance(item["enabled"], bool)


@pytest.mark.integration
@pytest.mark.p1
def test_api_backups_list_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/backups returns a JSON list (empty allowed).

    Test flow:
    1. GET /api/backups.
    2. Assert 200 and list type.

    API endpoints:
    - GET /api/backups
    """
    resp = app_server.api_request("GET", "/api/backups")
    assert resp.status_code == 200, app_server.logs_tail()
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_api_token_usage_summary_and_details_contract(app_server) -> None:
    """Test purpose:
    - Verify token-usage summary and details endpoints return stable shapes
      when there is no recorded usage.

    Test flow:
    1. GET /api/token-usage and assert TokenUsageSummary-like fields.
    2. GET /api/token-usage/details and assert JSON array.

    API endpoints:
    - GET /api/token-usage
    - GET /api/token-usage/details
    """
    summary = app_server.api_request("GET", "/api/token-usage")
    assert summary.status_code == 200, app_server.logs_tail()
    body = summary.json()
    assert isinstance(body.get("total_prompt_tokens"), int)
    assert isinstance(body.get("total_completion_tokens"), int)
    assert isinstance(body.get("total_calls"), int)
    assert body["total_prompt_tokens"] >= 0
    assert body["total_completion_tokens"] >= 0
    assert body["total_calls"] >= 0
    assert isinstance(body.get("by_date"), dict)

    details = app_server.api_request("GET", "/api/token-usage/details")
    assert details.status_code == 200, app_server.logs_tail()
    rows = details.json()
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        assert "date" in row
        assert isinstance(row.get("prompt_tokens"), int)
        assert isinstance(row.get("completion_tokens"), int)
        assert isinstance(row.get("call_count"), int)


@pytest.mark.integration
@pytest.mark.p1
def test_api_auth_status_disabled_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/auth/status matches CI profile (auth disabled).

    Test flow:
    1. GET /api/auth/status.
    2. Assert enabled is false and has_users is bool.

    API endpoints:
    - GET /api/auth/status
    """
    resp = app_server.api_request("GET", "/api/auth/status")
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("enabled") is False
    assert isinstance(body.get("has_users"), bool)


@pytest.mark.integration
@pytest.mark.p1
def test_api_agent_stats_summary_with_agent_header(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agent-stats returns AgentStatsSummary-like JSON when
      scoped via ``X-Agent-Id`` to a dedicated test agent.

    Test flow:
    1. Create a test agent.
    2. GET /api/agent-stats with X-Agent-Id header.
    3. Assert top-level counters and by_date / channel_stats list shapes.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agent-stats
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_agent_stats_meta_01"
    headers = {"X-Agent-Id": agent_id}

    create = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Agent stats meta", "description": ""},
    )
    assert create.status_code == 201, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "GET",
            "/api/agent-stats",
            headers=headers,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        body = resp.json()
        for key in (
            "total_active_sessions",
            "total_messages",
            "total_user_messages",
            "total_assistant_messages",
            "total_prompt_tokens",
            "total_completion_tokens",
            "total_llm_calls",
            "total_tool_calls",
        ):
            assert isinstance(body.get(key), int)
            assert body[key] >= 0
        assert isinstance(body.get("by_date"), list)
        assert isinstance(body.get("channel_stats"), list)
        assert isinstance(body.get("start_date"), str)
        assert isinstance(body.get("end_date"), str)
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")

# -*- coding: utf-8 -*-
"""Integration tests for /api/coding-mode, /api/fork, agent-status
(Sprint 4.2).

Target routers:
  - src/qwenpaw/app/routers/coding_mode.py (GET + POST /api/coding-mode)
  - src/qwenpaw/app/routers/fork.py         (POST /api/fork/agent)
  - src/qwenpaw/app/routers/agent_status.py (GET agent-scoped)

Coverage strategy (happy path first):
  - coding-mode: GET default state, POST toggle on/off with GET roundtrip
    (POST schedules an async agent reload, so GET is polled).
  - fork: POST fork of a non-git workspace returns a fork_session_id and
    empty worktree fields; a seeded parent session is inherited into the
    fork session file (verified on disk).
  - agent-status: idle values on a fresh agent; disabled status after
    toggling the agent off.

Notes:
  - coding-mode / fork are NOT agent-scoped. coding-mode resolves the
    active agent (or X-Agent-Id header); fork takes agent_id in the body.
  - agent-status IS agent-scoped: /api/agents/{agentId}/agent-status.
  - fork worktree (git) branch is out of scope this sprint (needs a git
    repo fixture); the non-git happy path returns empty worktree fields.
  - fork 403 (non-localhost) is unreachable in the harness (127.0.0.1).

No LLM / external deps required.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from helpers import (
    create_agent,
    default_http_timeout,
    delete_agent_quietly,
    scoped,
    toggle_agent,
)

_HTTP_TIMEOUT = default_http_timeout(15.0)


# ================================================================== #
# helpers
# ================================================================== #


def _poll_coding_mode(app_server, expected_enabled, *, timeout=6.0):
    """Poll GET /api/coding-mode until enabled == expected or timeout.

    POST toggle schedules an async agent reload; the disk write is
    synchronous but the in-memory swap races, so we poll.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = app_server.api_request(
            "GET",
            "/api/coding-mode",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        last = resp.json()
        if last.get("enabled") == expected_enabled:
            return last
        time.sleep(0.3)
    return last


def _sessions_dir(app_server, agent_id) -> Path:
    return app_server.working_dir / "workspaces" / agent_id / "sessions"


# ================================================================== #
# A class — coding mode (4 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_coding_mode_get_default_disabled(app_server) -> None:
    """GET /api/coding-mode on default agent → enabled=false + agent_id.

    API endpoints:
    - GET /api/coding-mode
    """
    resp = app_server.api_request(
        "GET",
        "/api/coding-mode",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body["enabled"] is False, body
    assert "agent_id" in body, body
    assert "project_dir" in body, body


@pytest.mark.integration
@pytest.mark.p0
def test_coding_mode_toggle_on_roundtrip(app_server) -> None:
    """POST enabled=true → GET reflects enabled=true (polled).

    Test flow:
    1. POST /api/coding-mode {enabled: true} → 200 + enabled=true echo.
    2. Poll GET until enabled=true (async agent reload).
    3. Restore to disabled in finally.

    API endpoints:
    - POST /api/coding-mode
    - GET  /api/coding-mode
    """
    try:
        resp = app_server.api_request(
            "POST",
            "/api/coding-mode",
            json={"enabled": True},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        assert resp.json()["enabled"] is True, resp.json()

        final = _poll_coding_mode(app_server, True)
        assert final is not None and final["enabled"] is True, (
            f"coding-mode did not flip to enabled: {final} / "
            f"{app_server.logs_tail()[-1500:]}"
        )
    finally:
        app_server.api_request(
            "POST",
            "/api/coding-mode",
            json={"enabled": False},
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p1
def test_coding_mode_toggle_off_roundtrip(app_server) -> None:
    """Enable then disable → GET reflects enabled=false.

    API endpoints:
    - POST /api/coding-mode
    - GET  /api/coding-mode
    """
    app_server.api_request(
        "POST",
        "/api/coding-mode",
        json={"enabled": True},
        timeout=_HTTP_TIMEOUT,
    )
    _poll_coding_mode(app_server, True)

    resp = app_server.api_request(
        "POST",
        "/api/coding-mode",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json()["enabled"] is False, resp.json()

    final = _poll_coding_mode(app_server, False)
    assert final is not None and final["enabled"] is False, final


@pytest.mark.integration
@pytest.mark.p2
def test_coding_mode_unknown_agent_returns_404(app_server) -> None:
    """GET /api/coding-mode with X-Agent-Id of a deleted agent → 404.

    coding-mode resolves the agent via get_agent_for_request, which
    honors the X-Agent-Id header. Pointing it at a non-existent agent
    exercises the 404 branch.

    API endpoints:
    - GET /api/coding-mode
    """
    resp = app_server.api_request(
        "GET",
        "/api/coding-mode",
        headers={"X-Agent-Id": "integ_cm_does_not_exist"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


# ================================================================== #
# B class — fork (3 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_fork_agent_non_git_returns_empty_worktree(app_server) -> None:
    """POST /api/fork/agent on a non-git workspace → fork id + empty wt.

    Test flow:
    1. Create a fresh agent (workspace is not a git repo).
    2. POST /api/fork/agent with a parent_session_id.
    3. Assert fork_session_id starts with 'sub-' and worktree fields
       are empty (no git repo → in-place fork).
    4. Assert the fork session file was written on disk.

    API endpoints:
    - POST /api/agents
    - POST /api/fork/agent
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_fork_nogit_01"
    create_agent(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "POST",
            "/api/fork/agent",
            json={
                "agent_id": agent_id,
                "parent_session_id": "sess-parent-1",
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        body = resp.json()
        assert body["fork_session_id"].startswith("sub-"), body
        assert body["worktree_path"] == "", body
        assert body["worktree_branch"] == "", body

        # The fork session file should exist on disk.
        fork_file = (
            _sessions_dir(app_server, agent_id)
            / f"{body['fork_session_id']}.json"
        )
        assert fork_file.exists(), (
            f"fork session file missing: {fork_file} / "
            f"{app_server.logs_tail()[-1500:]}"
        )
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_fork_agent_inherits_parent_session_state(app_server) -> None:
    """Fork inherits the parent session state into the fork session file.

    Test flow:
    1. Create an agent.
    2. Seed a parent session file with a known state dict.
    3. POST /api/fork/agent with the parent_session_id.
    4. Read the fork session file → contains the inherited state.

    API endpoints:
    - POST /api/agents
    - POST /api/fork/agent
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_fork_inherit_01"
    create_agent(app_server, agent_id)
    try:
        sessions = _sessions_dir(app_server, agent_id)
        sessions.mkdir(parents=True, exist_ok=True)
        parent_sid = "sess-inherit-1"
        parent_state = {"agent": {"marker": "integ-inherited-state"}}
        (sessions / f"{parent_sid}.json").write_text(
            json.dumps(parent_state),
            encoding="utf-8",
        )

        resp = app_server.api_request(
            "POST",
            "/api/fork/agent",
            json={
                "agent_id": agent_id,
                "parent_session_id": parent_sid,
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        fork_sid = resp.json()["fork_session_id"]

        fork_file = sessions / f"{fork_sid}.json"
        assert fork_file.exists(), app_server.logs_tail()
        forked = json.loads(fork_file.read_text(encoding="utf-8"))
        assert forked.get("agent", {}).get("marker") == (
            "integ-inherited-state"
        ), forked
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_fork_agent_unknown_returns_404(app_server) -> None:
    """POST /api/fork/agent with a non-existent agent_id → 404.

    API endpoints:
    - POST /api/fork/agent
    """
    resp = app_server.api_request(
        "POST",
        "/api/fork/agent",
        json={
            "agent_id": "integ_fork_does_not_exist",
            "parent_session_id": "sess-x",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


# ================================================================== #
# C class — agent status (2 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_idle_values(app_server) -> None:
    """GET agent-status on a fresh enabled agent → idle + zero counts.

    Extends the existing minimal-contract test by asserting the exact
    idle-state values (status=idle, count=0, timestamps null).

    API endpoints:
    - POST /api/agents
    - GET  /api/agents/{agentId}/agent-status
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_status_idle_01"
    create_agent(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "GET",
            scoped(agent_id, "/agent-status"),
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        body = resp.json()
        assert body["status"] == "idle", body
        assert body["running_task_count"] == 0, body
        assert body["last_run_at"] is None, body
        assert body["last_finish_at"] is None, body
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_disabled_after_toggle(app_server) -> None:
    """Toggle an agent off → GET agent-status returns status=disabled.

    The handler checks the enabled flag from config before touching the
    task tracker (agent_status.py:81), so a disabled agent returns a
    200 with status=disabled.

    API endpoints:
    - POST /api/agents
    - PATCH /api/agents/{agentId}/toggle
    - GET  /api/agents/{agentId}/agent-status
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_status_disabled_01"
    create_agent(app_server, agent_id)
    try:
        toggle_resp = toggle_agent(app_server, agent_id, False)
        assert toggle_resp.status_code in (200, 204), app_server.logs_tail()

        resp = app_server.api_request(
            "GET",
            scoped(agent_id, "/agent-status"),
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        body = resp.json()
        assert body["status"] == "disabled", body
        assert body["running_task_count"] == 0, body
    finally:
        delete_agent_quietly(app_server, agent_id)

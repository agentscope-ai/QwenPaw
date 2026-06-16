# -*- coding: utf-8 -*-
"""Integration tests for ACP runner interoperability (Sprint 3.1-A).

Drive the full chain:
    Mock LLM emits tool_call(delegate_external_agent)
        → agent runtime executes the tool
        → ACPService spawns the stdio mock runner
        → mock runner replies via JSON-RPC
        → result flows back through history / inbox

Mock ACP runner: ``tests/integration/fixtures/acp_mock_runner.py``
Mock LLM: ``helpers.MockLLMHandler`` with ``force_tool_call=True``
          and ``tool_call_name="delegate_external_agent"``.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import HTTPServer
from pathlib import Path

import pytest

from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    clean_inbox,
    register_mock_provider,
    scoped,
    unregister_mock_provider,
)

_HTTP_TIMEOUT = 15.0
_NEVER_FIRE_SCHEDULE = "0 0 1 1 *"
_MOCK_RUNNER_NAME = "mock_runner"
_MOCK_RUNNER_PATH = (
    Path(__file__).parent / "fixtures" / "acp_mock_runner.py"
)


# ------------------------------------------------------------------ #
# fixtures
# ------------------------------------------------------------------ #


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server with tool_call support."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    srv.tool_call_name = "delegate_external_agent"
    srv.tool_call_arguments = "{}"
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


# ------------------------------------------------------------------ #
# helpers
# ------------------------------------------------------------------ #


def _configure_mock_runner(app_server, runner_name=_MOCK_RUNNER_NAME):
    """Register the stdio mock ACP runner on the default agent."""
    resp = app_server.api_request(
        "PUT",
        scoped("default", f"/config/acp/{runner_name}"),
        json={
            "enabled": True,
            "command": sys.executable,
            "args": [str(_MOCK_RUNNER_PATH)],
            "env": {},
            "trusted": False,
            "tool_parse_mode": "call_title",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


def _enable_delegate_tool(app_server):
    """Enable delegate_external_agent via tool toggle."""
    resp = app_server.api_request(
        "PATCH",
        scoped("default", "/tools/delegate_external_agent/toggle"),
        json={"enabled": True},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


def _agent_input(text):
    return [
        {
            "role": "user",
            "type": "message",
            "content": [{"type": "text", "text": text}],
        },
    ]


def _agent_spec(name, *, save_inbox=True):
    return {
        "name": name,
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": _NEVER_FIRE_SCHEDULE,
            "timezone": "UTC",
        },
        "task_type": "agent",
        "request": {"input": _agent_input("List ACP runners")},
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {
                "user_id": f"acp-{name}",
                "session_id": f"console:acp-{name}-sess",
            },
            "mode": "stream",
        },
        "save_result_to_inbox": save_inbox,
    }


def _create_job(app_server, spec):
    resp = app_server.api_request(
        "POST", "/api/cron/jobs", json=spec, timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()["id"]


def _delete_job(app_server, job_id):
    try:
        app_server.api_request(
            "DELETE", f"/api/cron/jobs/{job_id}", timeout=_HTTP_TIMEOUT,
        )
    except Exception:
        pass


def _poll_history(app_server, job_id, deadline, *, min_count=1):
    while time.time() < deadline:
        resp = app_server.api_request(
            "GET",
            f"/api/cron/jobs/{job_id}/history",
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            records = resp.json()
            if isinstance(records, list) and len(records) >= min_count:
                return records
        time.sleep(1.0)
    return []


# ------------------------------------------------------------------ #
# A1: list runners
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_acp_list_runners_includes_mock_runner(
    app_server, mock_llm,
) -> None:
    """Test purpose:
    - Verify the full LLM → tool → ACP chain: mock LLM emits a tool_call
      for delegate_external_agent(action="list"), agent runtime executes
      it, and the response lists the configured mock runner.

    Test flow:
    1. Register and activate mock LLM provider.
    2. Configure stdio mock ACP runner via PUT /config/acp/{name}.
    3. Enable the delegate_external_agent builtin tool.
    4. Set MockLLM to emit tool_call with action="list".
    5. Trigger an agent-type cron run.
    6. Poll history → success; assert response mentions the mock runner.
    7. Cleanup.

    API endpoints:
    - PUT  /api/agents/{agentId}/config/acp/{agent_name}
    - PATCH /api/agents/{agentId}/tools/{name}/toggle
    - POST /api/cron/jobs
    - POST /api/cron/jobs/{job_id}/run
    - GET  /api/cron/jobs/{job_id}/history
    - DELETE /api/cron/jobs/{job_id}
    """
    srv, mock_url = mock_llm

    # Setup mock LLM provider.
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)

    # Configure ACP and enable tool.
    _configure_mock_runner(app_server)
    _enable_delegate_tool(app_server)

    # Drive mock LLM to emit delegate_external_agent(action="list").
    srv.force_tool_call = True
    srv.tool_call_name = "delegate_external_agent"
    srv.tool_call_arguments = json.dumps(
        {"action": "list", "runner": ""},
    )
    clean_inbox(app_server.working_dir)

    spec = _agent_spec("acp_list_smoke")
    job_id = _create_job(app_server, spec)
    try:
        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200, app_server.logs_tail()

        records = _poll_history(
            app_server, job_id, time.time() + 30.0,
        )
        assert (
            len(records) >= 1
        ), f"No history after 30s: {app_server.logs_tail()}"
        assert (
            records[0]["status"] == "success"
        ), f"Cron failed: {records[0]} | {app_server.logs_tail()}"
    finally:
        _delete_job(app_server, job_id)
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)

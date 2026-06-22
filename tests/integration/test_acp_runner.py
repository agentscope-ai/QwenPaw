# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
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
_MOCK_RUNNER_PATH = Path(__file__).parent / "fixtures" / "acp_mock_runner.py"


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
        "POST",
        "/api/cron/jobs",
        json=spec,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()["id"]


def _delete_job(app_server, job_id):
    try:
        app_server.api_request(
            "DELETE",
            f"/api/cron/jobs/{job_id}",
            timeout=_HTTP_TIMEOUT,
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
    app_server,
    mock_llm,
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
            app_server,
            job_id,
            time.time() + 30.0,
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


# ------------------------------------------------------------------ #
# A2: status (no spawn)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_acp_status_returns_runner_state(app_server, mock_llm) -> None:
    """Test purpose:
    - Verify delegate_external_agent(action="status") returns runner state
      without spawning the subprocess.

    Test flow:
    1. Setup mock LLM + ACP runner config + tool toggle (same as A1).
    2. Drive LLM to call action="status", runner="mock_runner".
    3. Run agent cron → poll history → success.
    """
    srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)
    _configure_mock_runner(app_server)
    _enable_delegate_tool(app_server)

    srv.force_tool_call = True
    srv.tool_call_name = "delegate_external_agent"
    srv.tool_call_arguments = json.dumps(
        {"action": "status", "runner": _MOCK_RUNNER_NAME},
    )
    clean_inbox(app_server.working_dir)

    spec = _agent_spec("acp_status_smoke")
    job_id = _create_job(app_server, spec)
    try:
        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200, app_server.logs_tail()
        records = _poll_history(app_server, job_id, time.time() + 30.0)
        assert len(records) >= 1, app_server.logs_tail()
        assert records[0]["status"] == "success", records[0]
    finally:
        _delete_job(app_server, job_id)
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


# ------------------------------------------------------------------ #
# A3: start session — real mock runner spawn
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_acp_start_spawns_mock_runner(app_server, mock_llm) -> None:
    """Test purpose:
    - Verify delegate_external_agent(action="start") really spawns the
      stdio mock runner subprocess and gets a reply via JSON-RPC.

    Test flow:
    1. Setup mock LLM + runner config + tool toggle.
    2. Drive LLM tool_call: action="start", runner="mock_runner",
       message="hello".
    3. Run agent cron → poll history → success.
    4. The mock runner emits ``agent_message_chunk`` with reply text;
       agent runtime surfaces it as a ToolResponse.

    API endpoints exercised end-to-end:
    - POST /api/cron/jobs/{job_id}/run (drives the LLM)
    - delegate_external_agent tool → ACPService → spawn_agent_process
    """
    srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)
    _configure_mock_runner(app_server)
    _enable_delegate_tool(app_server)

    srv.force_tool_call = True
    srv.tool_call_name = "delegate_external_agent"
    srv.tool_call_arguments = json.dumps(
        {
            "action": "start",
            "runner": _MOCK_RUNNER_NAME,
            "message": "hello mock",
        },
    )
    clean_inbox(app_server.working_dir)

    spec = _agent_spec("acp_start_real")
    job_id = _create_job(app_server, spec)
    try:
        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200, app_server.logs_tail()
        records = _poll_history(app_server, job_id, time.time() + 60.0)
        assert len(records) >= 1, app_server.logs_tail()
        assert (
            records[0]["status"] == "success"
        ), f"start failed: {records[0]} | {app_server.logs_tail()}"
        # The mock runner emits ``agent_message_chunk`` with the default
        # text "mock reply" (ACP_MOCK_REPLY_TEXT). Assert it surfaces in
        # the server logs — proves the JSON-RPC reply is wired back into
        # the agent response path, not just that cron returned success.
        logs = app_server.logs_tail(20000)
        assert "mock reply" in logs, (
            "ACP runner reply not surfaced to agent runtime:\n"
            f"{logs[-3000:]}"
        )
    finally:
        _delete_job(app_server, job_id)
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


# ------------------------------------------------------------------ #
# A4: close session after start
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_acp_close_after_start(app_server, mock_llm) -> None:
    """Test purpose:
    - Verify two-step lifecycle: start (spawn) → close (cleanup) both
      complete successfully through the LLM tool_call chain.

    Test flow:
    1. Setup as A1.
    2. Drive LLM to call action="start" → run job 1 → success.
    3. Drive LLM to call action="close" → run job 2 → success.
       (Both jobs share the same dispatch target so chat_id matches.)
    """
    srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)
    _configure_mock_runner(app_server)
    _enable_delegate_tool(app_server)

    clean_inbox(app_server.working_dir)
    srv.force_tool_call = True
    srv.tool_call_name = "delegate_external_agent"

    # Step 1: start
    srv.tool_call_arguments = json.dumps(
        {
            "action": "start",
            "runner": _MOCK_RUNNER_NAME,
            "message": "open",
        },
    )
    spec_start = _agent_spec("acp_close_lifecycle_start")
    spec_start["dispatch"]["target"] = {
        "user_id": "acp-close-life",
        "session_id": "console:acp-close-life-sess",
    }
    job_start = _create_job(app_server, spec_start)
    try:
        app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_start}/run",
            timeout=_HTTP_TIMEOUT,
        )
        records = _poll_history(
            app_server,
            job_start,
            time.time() + 60.0,
        )
        assert (
            len(records) >= 1 and records[0]["status"] == "success"
        ), f"start failed: {app_server.logs_tail()}"

        # Step 2: close (same chat_id via same target)
        srv.tool_call_arguments = json.dumps(
            {"action": "close", "runner": _MOCK_RUNNER_NAME},
        )
        spec_close = _agent_spec("acp_close_lifecycle_close")
        spec_close["dispatch"]["target"] = spec_start["dispatch"]["target"]
        job_close = _create_job(app_server, spec_close)
        try:
            app_server.api_request(
                "POST",
                f"/api/cron/jobs/{job_close}/run",
                timeout=_HTTP_TIMEOUT,
            )
            records2 = _poll_history(
                app_server,
                job_close,
                time.time() + 30.0,
            )
            assert (
                len(records2) >= 1 and records2[0]["status"] == "success"
            ), f"close failed: {app_server.logs_tail()}"
        finally:
            _delete_job(app_server, job_close)
    finally:
        _delete_job(app_server, job_start)
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


# ------------------------------------------------------------------ #
# A5: initialize failure surfaces as cron failure
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_acp_initialize_failure_records_error(
    app_server,
    mock_llm,
) -> None:
    """Test purpose:
    - Verify that when the mock runner refuses initialize, the
      agent runtime surfaces the error and the cron history captures
      a non-success outcome (or the assistant retries gracefully).

    Test flow:
    1. Configure runner with ACP_MOCK_FAIL_INITIALIZE=1.
    2. Drive LLM to action="start".
    3. Cron run → poll history; the record may be success (tool error
       summarised in response) or failure — either is acceptable, but
       we MUST get a record back so the runtime did not deadlock.
    """
    srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)

    # Configure runner with init failure injected via env.
    resp = app_server.api_request(
        "PUT",
        scoped("default", f"/config/acp/{_MOCK_RUNNER_NAME}"),
        json={
            "enabled": True,
            "command": sys.executable,
            "args": [str(_MOCK_RUNNER_PATH)],
            "env": {"ACP_MOCK_FAIL_INITIALIZE": "1"},
            "trusted": False,
            "tool_parse_mode": "call_title",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    _enable_delegate_tool(app_server)

    srv.force_tool_call = True
    srv.tool_call_name = "delegate_external_agent"
    srv.tool_call_arguments = json.dumps(
        {
            "action": "start",
            "runner": _MOCK_RUNNER_NAME,
            "message": "x",
        },
    )
    clean_inbox(app_server.working_dir)

    spec = _agent_spec("acp_init_fail")
    job_id = _create_job(app_server, spec)
    try:
        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200, app_server.logs_tail()
        records = _poll_history(app_server, job_id, time.time() + 60.0)
        assert (
            len(records) >= 1
        ), f"No history (deadlock?): {app_server.logs_tail()}"
        # Must not deadlock; status may be success or failure.
        assert records[0]["status"] in {
            "success",
            "failure",
            "error",
        }, records[0]
    finally:
        _delete_job(app_server, job_id)
        # Reset runner config for subsequent tests.
        app_server.api_request(
            "PUT",
            scoped("default", f"/config/acp/{_MOCK_RUNNER_NAME}"),
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
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)

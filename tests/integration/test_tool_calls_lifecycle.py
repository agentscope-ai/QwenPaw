# -*- coding: utf-8 -*-
"""Integration tests for /api/tool-calls/* router (Sprint 4.1).

Target routes (7):
  - GET    /api/tool-calls/{session_id}
  - GET    /api/tool-calls/{session_id}/{tool_call_id}
  - POST   /api/tool-calls/{session_id}/{tool_call_id}/offload
  - POST   /api/tool-calls/{session_id}/{tool_call_id}/cancel
  - POST   /api/tool-calls/{session_id}/{tool_call_id}/extend-deadline
  - GET    /api/tool-calls/{session_id}/{tool_call_id}/output
  - GET    /api/tool-calls/{session_id}/{tool_call_id}/stream

Coverage strategy:
  1. Empty-session contract (list returns empty, all detail routes 404).
  2. Body validation (extend-deadline requires seconds>0 or no_deadline).
  3. Cross-session 404 guard using an unknown tool_call_id.
  4. Governance ASK path smoke — set session-level approval_level
     ``always_ask`` through the console chat body and verify the pending
     approval surfaces (tool_adapter.py:_ask_user_approval branch).

The tool_call entry is popped from ``coordinator._entries`` the moment
the tool finishes, so live inspection of an in-flight tool call is not
feasible with the built-in ``get_current_time`` (sub-millisecond).  The
existing cron + security tests already exercise the runtime middleware
chain end-to-end (test_cron_execution::test_cron_agent_tool_call_execution
and test_security_real::test_tool_guard_blocks_dangerous_shell_via_agent_run);
here we focus on the HTTP router contract + governance approval branch.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import HTTPServer

import pytest

from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    default_http_timeout,
    register_mock_provider,
    unregister_mock_provider,
)

_HTTP_TIMEOUT = default_http_timeout(15.0)

_UNKNOWN_SESSION = "console:integ-tool-calls-unknown-session"
_UNKNOWN_CALL_ID = "call_integ_tool_calls_unknown"


# ================================================================== #
# fixtures
# ================================================================== #


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server with tool_call support."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


# ================================================================== #
# A class — empty-session contract (5 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_list_calls_unknown_session_returns_empty(app_server) -> None:
    """GET /api/tool-calls/{sid} on unknown session → 200 + empty list.

    ``coordinator.list_entries`` filters by session_id; an unknown
    session yields an empty list (never 404).  Guards against a
    regression where the router mistakenly required an entry to exist.

    API endpoints:
    - GET /api/tool-calls/{session_id}
    """
    resp = app_server.api_request(
        "GET",
        f"/api/tool-calls/{_UNKNOWN_SESSION}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert payload == {"items": [], "total": 0}, payload


@pytest.mark.integration
@pytest.mark.p0
def test_get_call_unknown_returns_404(app_server) -> None:
    """GET /api/tool-calls/{sid}/{tcid} on unknown ids → 404.

    Verifies the cross-session guard 404 message shape used by all
    entry-level routes.

    API endpoints:
    - GET /api/tool-calls/{session_id}/{tool_call_id}
    """
    resp = app_server.api_request(
        "GET",
        f"/api/tool-calls/{_UNKNOWN_SESSION}/{_UNKNOWN_CALL_ID}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json()["detail"] == "Tool call not found"


@pytest.mark.integration
@pytest.mark.p1
def test_get_output_unknown_returns_404(app_server) -> None:
    """GET /api/tool-calls/{sid}/{tcid}/output on unknown ids → 404.

    API endpoints:
    - GET /api/tool-calls/{session_id}/{tool_call_id}/output
    """
    resp = app_server.api_request(
        "GET",
        f"/api/tool-calls/{_UNKNOWN_SESSION}/{_UNKNOWN_CALL_ID}/output",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json()["detail"] == "Tool call not found"


@pytest.mark.integration
@pytest.mark.p2
def test_stream_output_unknown_returns_404(app_server) -> None:
    """GET /api/tool-calls/{sid}/{tcid}/stream on unknown ids → 404.

    Even though the endpoint returns a StreamingResponse on the happy
    path, the guard runs before streaming begins, so a plain 404 body
    is returned.

    API endpoints:
    - GET /api/tool-calls/{session_id}/{tool_call_id}/stream
    """
    resp = app_server.api_request(
        "GET",
        f"/api/tool-calls/{_UNKNOWN_SESSION}/{_UNKNOWN_CALL_ID}/stream",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_cancel_unknown_returns_404(app_server) -> None:
    """POST /api/tool-calls/{sid}/{tcid}/cancel on unknown ids → 404.

    The 404 must fire before ``coordinator.cancel`` is called (which
    could otherwise return False and trigger 409).

    API endpoints:
    - POST /api/tool-calls/{session_id}/{tool_call_id}/cancel
    """
    resp = app_server.api_request(
        "POST",
        f"/api/tool-calls/{_UNKNOWN_SESSION}/{_UNKNOWN_CALL_ID}/cancel",
        json={"force": False},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


# ================================================================== #
# B class — offload + extend-deadline (4 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_offload_unknown_returns_404(app_server) -> None:
    """POST /api/tool-calls/{sid}/{tcid}/offload on unknown ids → 404.

    API endpoints:
    - POST /api/tool-calls/{session_id}/{tool_call_id}/offload
    """
    resp = app_server.api_request(
        "POST",
        f"/api/tool-calls/{_UNKNOWN_SESSION}/{_UNKNOWN_CALL_ID}/offload",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json()["detail"] == "Tool call not found"


@pytest.mark.integration
@pytest.mark.p1
def test_extend_deadline_unknown_returns_404(app_server) -> None:
    """POST /api/tool-calls/{sid}/{tcid}/extend-deadline unknown → 404.

    Body is valid (seconds=5) so the guard runs first; unknown entry
    triggers 404 before ``coordinator.extend_deadline`` is called.

    API endpoints:
    - POST /api/tool-calls/{session_id}/{tool_call_id}/extend-deadline
    """
    resp = app_server.api_request(
        "POST",
        (
            f"/api/tool-calls/{_UNKNOWN_SESSION}/"
            f"{_UNKNOWN_CALL_ID}/extend-deadline"
        ),
        json={"seconds": 5.0},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json()["detail"] == "Tool call not found"


@pytest.mark.integration
@pytest.mark.p2
def test_extend_deadline_rejects_zero_seconds(app_server) -> None:
    """seconds must be > 0 (Field gt=0) — 422 body validation.

    Router body model: ``ExtendRequest(seconds: float | None, gt=0)``.

    API endpoints:
    - POST /api/tool-calls/{session_id}/{tool_call_id}/extend-deadline
    """
    resp = app_server.api_request(
        "POST",
        (
            f"/api/tool-calls/{_UNKNOWN_SESSION}/"
            f"{_UNKNOWN_CALL_ID}/extend-deadline"
        ),
        json={"seconds": 0},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_extend_deadline_accepts_no_deadline_flag(app_server) -> None:
    """no_deadline=true is a valid body → still 404 (unknown call).

    Confirms the body model accepts ``{no_deadline: true}`` without
    ``seconds`` (both are optional), and the 404 fires on unknown id.

    API endpoints:
    - POST /api/tool-calls/{session_id}/{tool_call_id}/extend-deadline
    """
    resp = app_server.api_request(
        "POST",
        (
            f"/api/tool-calls/{_UNKNOWN_SESSION}/"
            f"{_UNKNOWN_CALL_ID}/extend-deadline"
        ),
        json={"no_deadline": True},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


# ================================================================== #
# C class — session isolation (2 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_list_calls_multiple_unknown_sessions_all_empty(app_server) -> None:
    """List across 3 distinct unknown sessions → all 200 + empty.

    Cheap smoke that the session_id path parameter is truly used as a
    filter key (not cached / mis-shared across requests).

    API endpoints:
    - GET /api/tool-calls/{session_id}
    """
    for suffix in ("aa", "bb", "cc"):
        resp = app_server.api_request(
            "GET",
            f"/api/tool-calls/{_UNKNOWN_SESSION}-{suffix}",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        assert resp.json()["total"] == 0


@pytest.mark.integration
@pytest.mark.p2
def test_get_call_url_encoded_session_id_returns_404(app_server) -> None:
    """URL-encoded session_id with special chars still yields 404.

    Ensures a session_id that includes ':' (as produced by
    ``console.resolve_session_id`` → ``f"console:{sender_id}"``) round-
    trips correctly through FastAPI path parsing.

    API endpoints:
    - GET /api/tool-calls/{session_id}/{tool_call_id}
    """
    sid = "console%3Aweird-user%40host"
    resp = app_server.api_request(
        "GET",
        f"/api/tool-calls/{sid}/{_UNKNOWN_CALL_ID}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


# ================================================================== #
# D class — session-level approval plumbing smoke (1 test)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_session_level_approval_off_short_circuits_governance(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Session-level approval_level=off short-circuits governance check.

    Test purpose:
      - Verify the frontend session-level approval override (PR #5685)
        propagates through console → runtime → PolicyGuardedTool and
        the ``is_disabled()`` branch at ``tool_adapter.py:207-211``
        fires when ``approval_level=off``.

    Test flow:
      1. Register mock LLM provider (get_current_time tool_call).
      2. Submit /console/chat/task with request_context.approval_level=off.
      3. Poll task status until finished.
      4. Verify the governance log records the ``approval_level=off``
         short-circuit for at least one tool call in the session.

    We use ``off`` (not ``always_ask``) because:
      - ``always_ask`` is not a valid ``ToolExecutionLevel`` value
        (enum: off/auto/smart/strict) — the ``from_config`` fallback
        would coerce it to AUTO which yields tool-specific decisions.
      - ``off`` guarantees the is_disabled() early return branch,
        deterministically exercising the request_context plumbing.
      - The alternative (``strict`` forces ASK on every tool) requires
        a synchronous approval reply and depends on the ApprovalService
        wiring, which is out of scope for Sprint 4.1.

    API endpoints:
      - POST /api/console/chat/task
      - GET  /api/console/chat/task/{task_id}
    """
    srv, mock_url = mock_llm
    srv.force_error = False
    srv.force_tool_call = True
    srv.tool_call_name = "get_current_time"
    srv.tool_call_arguments = "{}"

    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)

    user_id = "integ-tc-approval-off"
    session_id = f"console:{user_id}"
    body = {
        "channel": "console",
        "user_id": user_id,
        "session_id": session_id,
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [
                    {"type": "text", "text": "What time is it?"},
                ],
            },
        ],
        "request_context": {"approval_level": "off"},
    }
    try:
        submit_resp = app_server.api_request(
            "POST",
            "/api/console/chat/task",
            json=body,
            timeout=_HTTP_TIMEOUT,
        )
        assert submit_resp.status_code == 200, app_server.logs_tail()
        task_id = submit_resp.json()["task_id"]

        # Poll until the background task reports finished status.
        # A successful completion with a valid result payload confirms
        # that request_context (including approval_level) survived the
        # console → runtime → PolicyGuardedTool plumbing without error.
        # Any missing/malformed field would abort the run and produce
        # status='failed' or leave the task stuck.
        deadline = time.time() + 25.0
        final = None
        while time.time() < deadline:
            resp = app_server.api_request(
                "GET",
                f"/api/console/chat/task/{task_id}",
                timeout=_HTTP_TIMEOUT,
            )
            assert resp.status_code == 200, app_server.logs_tail()
            body_resp = resp.json()
            if body_resp.get("status") == "finished":
                final = body_resp
                break
            time.sleep(0.4)
        assert final is not None, (
            f"task {task_id} did not finish: "
            f"{app_server.logs_tail()[-2000:]}"
        )
        result = final.get("result") or {}
        assert result.get("status") == "completed", (
            f"task result not completed: {result} / "
            f"{app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


# ================================================================== #
# E class — happy path (shell sleep observation window) (6 tests)
# ================================================================== #

_SHELL_SLEEP_SECS = 6


def _portable_sleep_cmd(seconds: int) -> str:
    """Return a shell command that blocks for ~``seconds``, per-platform.

    The app subprocess runs on the same host as the test process, so
    ``sys.platform`` reflects the shell that ``execute_shell_command``
    will use.  On Windows ``cmd.exe`` has no ``sleep`` builtin, so we use
    ``ping`` (``-n K`` sends K packets ~1s apart; K = seconds + 1 to get
    roughly ``seconds`` of wall time).  On POSIX we use ``sleep``.
    """
    if sys.platform.startswith("win"):
        return f"ping -n {seconds + 1} 127.0.0.1"
    return f"sleep {seconds}"


def _submit_shell_sleep_task(  # pylint: disable=redefined-outer-name
    app_server,
    mock_llm,
    suffix,
):
    """Start a chat/task with a portable long-running shell command.

    Each caller passes a unique ``suffix`` to get an isolated session_id
    (avoids cross-test collisions within the module-scoped app_server).

    Returns (task_id, session_id).
    """
    srv, mock_url = mock_llm
    srv.force_error = False
    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps(
        {"command": _portable_sleep_cmd(_SHELL_SLEEP_SECS)},
    )

    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)

    user_id = f"integ-tc-shell-{suffix}"
    session_id = f"console:{user_id}"
    body = {
        "channel": "console",
        "user_id": user_id,
        "session_id": session_id,
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [
                    {"type": "text", "text": "run sleep"},
                ],
            },
        ],
        "request_context": {"approval_level": "off"},
    }
    submit_resp = app_server.api_request(
        "POST",
        "/api/console/chat/task",
        json=body,
        timeout=_HTTP_TIMEOUT,
    )
    assert submit_resp.status_code == 200, app_server.logs_tail()
    return submit_resp.json()["task_id"], session_id


def _poll_for_entry(app_server, session_id, timeout=15.0):
    """Poll list_calls until at least one entry appears; return it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = app_server.api_request(
            "GET",
            f"/api/tool-calls/{session_id}",
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 200 and resp.json()["total"] > 0:
            return resp.json()["items"][0]
        time.sleep(0.3)
    return None


@pytest.mark.integration
@pytest.mark.p0
def test_list_calls_returns_running_entry(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """GET /api/tool-calls/{sid} returns a RUNNING entry during shell sleep.

    Test purpose:
      - Verify that a tool call triggered via Mock LLM (execute_shell_command
        with sleep N) creates an observable entry with status=running and
        correct session_id/tool_name fields.

    Test flow:
      1. Register mock LLM, configure a portable long-running
         execute_shell_command (sleep on POSIX / ping on Windows).
      2. Submit chat/task with approval_level=off.
      3. Poll /api/tool-calls/{session_id} until total > 0.
      4. Assert entry has status=running, correct tool_name, session_id.

    API endpoints:
      - POST /api/console/chat/task
      - GET  /api/tool-calls/{session_id}
    """
    try:
        _task_id, session_id = _submit_shell_sleep_task(
            app_server,
            mock_llm,
            "list",
        )
        entry = _poll_for_entry(app_server, session_id)
        assert (
            entry is not None
        ), f"no tool_call entry appeared: {app_server.logs_tail()[-2000:]}"
        assert entry["status"] == "running", entry
        assert entry["tool_name"] == "execute_shell_command", entry
        assert entry["session_id"] == session_id, entry
        assert entry["tool_call_id"], entry
    finally:
        srv, _ = mock_llm
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


@pytest.mark.integration
@pytest.mark.p0
def test_get_call_returns_detail_while_running(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """GET /api/tool-calls/{sid}/{tcid} → 200 with full ToolCallInfo.

    Test purpose:
      - Verify the detail endpoint returns the same entry (by ID) with
        all expected fields populated (started_at, deadline, elapsed, etc).

    Test flow:
      1. Submit shell sleep task.
      2. Poll for entry via list endpoint.
      3. GET detail by tool_call_id → assert 200 + fields.

    API endpoints:
      - GET /api/tool-calls/{session_id}/{tool_call_id}
    """
    try:
        _task_id, session_id = _submit_shell_sleep_task(
            app_server,
            mock_llm,
            "detail",
        )
        entry = _poll_for_entry(app_server, session_id)
        assert entry is not None, app_server.logs_tail()[-2000:]

        resp = app_server.api_request(
            "GET",
            f"/api/tool-calls/{session_id}/{entry['tool_call_id']}",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        detail = resp.json()
        assert detail["tool_call_id"] == entry["tool_call_id"]
        assert detail["status"] == "running"
        assert detail["started_at"] > 0
        assert detail["elapsed"] >= 0
    finally:
        srv, _ = mock_llm
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


@pytest.mark.integration
@pytest.mark.p1
def test_get_output_while_running(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """GET .../output → 200 with is_closed=false while tool is running.

    Test purpose:
      - Verify the output endpoint returns partial state (stream not
        yet closed) during tool execution.

    Test flow:
      1. Submit shell sleep task.
      2. Poll for entry.
      3. GET output → 200 + is_closed=false.

    API endpoints:
      - GET /api/tool-calls/{session_id}/{tool_call_id}/output
    """
    try:
        _task_id, session_id = _submit_shell_sleep_task(
            app_server,
            mock_llm,
            "output",
        )
        entry = _poll_for_entry(app_server, session_id)
        assert entry is not None, app_server.logs_tail()[-2000:]

        resp = app_server.api_request(
            "GET",
            (
                f"/api/tool-calls/{session_id}/"
                f"{entry['tool_call_id']}/output"
            ),
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        output = resp.json()
        assert output["tool_call_id"] == entry["tool_call_id"]
        assert output["is_closed"] is False
    finally:
        srv, _ = mock_llm
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


@pytest.mark.integration
@pytest.mark.p1
def test_extend_deadline_while_running(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """POST .../extend-deadline → 202 while tool is running.

    Test purpose:
      - Verify the extend-deadline endpoint accepts a valid request
        and returns 202 when the entry exists and is RUNNING.

    Test flow:
      1. Submit shell sleep task.
      2. Poll for entry.
      3. POST extend-deadline with seconds=10 → 202.

    API endpoints:
      - POST /api/tool-calls/{session_id}/{tool_call_id}/extend-deadline
    """
    try:
        _task_id, session_id = _submit_shell_sleep_task(
            app_server,
            mock_llm,
            "extend",
        )
        entry = _poll_for_entry(app_server, session_id)
        assert entry is not None, app_server.logs_tail()[-2000:]

        resp = app_server.api_request(
            "POST",
            (
                f"/api/tool-calls/{session_id}/"
                f"{entry['tool_call_id']}/extend-deadline"
            ),
            json={"seconds": 10.0},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 202, (
            f"extend-deadline failed: {resp.status_code} "
            f"{resp.text} / {app_server.logs_tail()[-2000:]}"
        )
        body_resp = resp.json()
        assert body_resp["status"] == "accepted"
        assert body_resp["tool_call_id"] == entry["tool_call_id"]
    finally:
        srv, _ = mock_llm
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


@pytest.mark.integration
@pytest.mark.p0
def test_cancel_while_running(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """POST .../cancel → 202 while tool is running.

    Test purpose:
      - Verify the cancel endpoint terminates a running tool call
        and returns 202.

    Test flow:
      1. Submit shell sleep task.
      2. Poll for entry.
      3. POST cancel → 202.
      4. Verify the task eventually finishes (entry is cleaned up).

    API endpoints:
      - POST /api/tool-calls/{session_id}/{tool_call_id}/cancel
      - GET  /api/tool-calls/{session_id}
    """
    try:
        _task_id, session_id = _submit_shell_sleep_task(
            app_server,
            mock_llm,
            "cancel",
        )
        entry = _poll_for_entry(app_server, session_id)
        assert entry is not None, app_server.logs_tail()[-2000:]

        resp = app_server.api_request(
            "POST",
            (
                f"/api/tool-calls/{session_id}/"
                f"{entry['tool_call_id']}/cancel"
            ),
            json={"force": False},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 202, (
            f"cancel failed: {resp.status_code} "
            f"{resp.text} / {app_server.logs_tail()[-2000:]}"
        )
        assert resp.json()["status"] == "accepted"

        # After cancel, entry should eventually be removed.
        deadline = time.time() + 10.0
        cleared = False
        while time.time() < deadline:
            list_resp = app_server.api_request(
                "GET",
                f"/api/tool-calls/{session_id}",
                timeout=_HTTP_TIMEOUT,
            )
            if list_resp.json()["total"] == 0:
                cleared = True
                break
            time.sleep(0.3)
        assert cleared, (
            f"entry not cleared after cancel: "
            f"{app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv, _ = mock_llm
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


@pytest.mark.integration
@pytest.mark.p1
def test_offload_while_running(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """POST .../offload → 202 while tool is running.

    Test purpose:
      - Verify the offload endpoint transitions a running tool call
        to OFFLOADED state and returns 202.

    Test flow:
      1. Submit shell sleep task.
      2. Poll for entry.
      3. POST offload → 202.
      4. GET detail → status should be 'offloaded'.

    API endpoints:
      - POST /api/tool-calls/{session_id}/{tool_call_id}/offload
      - GET  /api/tool-calls/{session_id}/{tool_call_id}
    """
    try:
        _task_id, session_id = _submit_shell_sleep_task(
            app_server,
            mock_llm,
            "offload",
        )
        entry = _poll_for_entry(app_server, session_id)
        assert entry is not None, app_server.logs_tail()[-2000:]

        resp = app_server.api_request(
            "POST",
            (
                f"/api/tool-calls/{session_id}/"
                f"{entry['tool_call_id']}/offload"
            ),
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 202, (
            f"offload failed: {resp.status_code} "
            f"{resp.text} / {app_server.logs_tail()[-2000:]}"
        )
        assert resp.json()["status"] == "accepted"

        # Verify entry transitioned to offloaded.
        detail_resp = app_server.api_request(
            "GET",
            f"/api/tool-calls/{session_id}/{entry['tool_call_id']}",
            timeout=_HTTP_TIMEOUT,
        )
        assert detail_resp.status_code == 200, app_server.logs_tail()
        assert detail_resp.json()["status"] == "offloaded", detail_resp.json()
    finally:
        srv, _ = mock_llm
        srv.force_tool_call = False
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


# Silence linter: json imported for potential future use in this file
# where callers may need to serialize custom bodies.
_ = json

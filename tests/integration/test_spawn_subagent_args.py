# -*- coding: utf-8 -*-
"""spawn_subagent argument coercion and background task lifecycle.

Covers the validation and coercion layer of
``agents/tools/agent_management.py`` (``_coerce_bool``,
``_coerce_timeout``, ``_normalize_str_list``, ``_normalize_batch``) plus
the background submission path and the real ``check_agent_task`` poll
that resolves a task the same turn submitted.

LLMs frequently mis-serialize tool arguments (booleans as strings, lists
as JSON strings, numbers as text). These tests drive each accepted and
each rejected shape through a real agent turn so the coercion branches
run inside the app subprocess and the resulting ERROR text is asserted.

API endpoints:
  - POST /api/console/chat/task  (drives a full agent turn)
  - GET  /api/console/chat/task/{task_id}
"""
from __future__ import annotations

import json
import re
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

_HTTP_TIMEOUT = default_http_timeout(60.0)

# Only the parent turn's prompt carries this marker, so the mock LLM
# forces the tool call there and answers the spawned subagent's own turn
# with plain text instead of forcing another spawn (which would recurse).
_PARENT_MARKER = "INTEG-SPAWN-PARENT"


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server with gated tool_call support."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    srv.force_tool_call_user_marker = _PARENT_MARKER
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.force_tool_call_user_marker = None
    srv.shutdown()


def _run_tool(
    app_server,
    *,
    user_id: str,
    prompt: str,
    poll_timeout: float = 240.0,
) -> dict:
    """Submit a chat task that triggers the forced tool; poll to end."""
    submit = app_server.api_request(
        "POST",
        "/api/console/chat/task",
        json={
            "channel": "console",
            "user_id": user_id,
            "session_id": f"console:{user_id}",
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "text", "text": prompt}],
                },
            ],
            "request_context": {"approval_level": "off"},
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert submit.status_code == 200, app_server.logs_tail()[-2000:]
    task_id = submit.json()["task_id"]
    deadline = time.time() + poll_timeout
    while time.time() < deadline:
        poll = app_server.api_request(
            "GET",
            f"/api/console/chat/task/{task_id}",
            timeout=default_http_timeout(15.0),
        )
        assert poll.status_code == 200, app_server.logs_tail()[-2000:]
        body = poll.json()
        if body.get("status") == "finished":
            return body
        time.sleep(0.4)
    raise AssertionError(
        "tool task did not finish: " + app_server.logs_tail()[-2000:],
    )


def _force(srv, name: str, arguments: dict) -> None:
    srv.force_tool_call = True
    srv.tool_call_name = name
    srv.tool_call_arguments = json.dumps(arguments)


def _body(final: dict) -> str:
    return json.dumps(final, ensure_ascii=False)


def _spawn(app_server, srv, mock_url, *, user_id: str, args: dict) -> str:
    """Force one spawn_subagent call and return the response JSON text."""
    _force(srv, "spawn_subagent", args)
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id=user_id,
            prompt=f"{_PARENT_MARKER} spawn a subagent",
        )
        assert final.get("status") == "finished", final
        return _body(final)
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


# =================== A. accepted (string) argument shapes ==================


@pytest.mark.integration
@pytest.mark.p1
def test_spawn_accepts_string_boolean_and_numeric_timeout(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """String "false" and "120" are coerced, not rejected.

    Test purpose:
      - Cover _coerce_bool's known-false-string branch and
        _coerce_timeout's numeric-string branch. Python's
        ``bool("false")`` is True, so a naive implementation would fork
        the subagent; the coercion must instead run the plain path and
        the turn must not report an ERROR.

    Test flow:
      1. Force spawn_subagent with fork="false", background="false",
         timeout="120".
      2. Assert the subagent produced a session marker and no ERROR.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-strbool",
        args={
            "task": "say hello",
            "fork": "false",
            "background": "false",
            "timeout": "120",
        },
    )
    assert "ERROR" not in body, body[:2000]
    assert "SESSION" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_accepts_json_array_string_for_allowed_tools(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """allowed_tools given as a JSON array string is parsed.

    Test purpose:
      - Cover _coerce_json_list's string branch: a naive ``list(value)``
        would split the string into characters, so the tool must parse
        the JSON and complete without an ERROR.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-jsonlist",
        args={
            "task": "say hello",
            "allowed_tools": '["get_current_time"]',
        },
    )
    assert "ERROR" not in body, body[:2000]
    assert "SESSION" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_accepts_empty_allowed_tools_list(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An empty allowed_tools list denies all tools but still runs.

    Test purpose:
      - Cover the ``allowed_tools=[]`` path, which is distinct from
        ``None`` (inherit everything) in
        _build_subagent_request_context.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-notools",
        args={"task": "say hello", "allowed_tools": []},
    )
    assert "ERROR" not in body, body[:2000]
    assert "SESSION" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_accepts_skills_whitelist(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A skills whitelist is normalized and passed through.

    Test purpose:
      - Cover the ``skills`` branch of _normalize_str_list and
        _build_subagent_request_context's subagent_skills key.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-skills",
        args={"task": "say hello", "skills": ["nonexistent-skill"]},
    )
    assert "ERROR" not in body, body[:2000]
    assert "SESSION" in body, body[:2000]


# ===================== B. rejected argument shapes =========================


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_rejects_ambiguous_boolean(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A non-boolean fork value is rejected with a clear message.

    Test purpose:
      - Cover _coerce_bool's raise path: "maybe" is neither a known
        true nor false token, so the tool must not silently treat it as
        truthy.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-badbool",
        args={"task": "say hello", "fork": "maybe"},
    )
    assert "ERROR" in body, body[:2000]
    assert "fork" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_rejects_non_positive_timeout(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A zero timeout is rejected rather than used.

    Test purpose:
      - Cover _coerce_timeout's ``as_int <= 0`` guard, which runs after
        int() truncation.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-badtimeout",
        args={"task": "say hello", "timeout": 0},
    )
    assert "ERROR" in body, body[:2000]
    assert "timeout" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_rejects_non_json_string_allowed_tools(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A bare (non-JSON) string for allowed_tools is rejected.

    Test purpose:
      - Cover _coerce_json_list's JSONDecodeError branch, which guards
        against character-splitting a plain tool name.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-badlist",
        args={"task": "say hello", "allowed_tools": "get_current_time"},
    )
    assert "ERROR" in body, body[:2000]
    assert "allowed_tools" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_rejects_task_and_batch_together(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """task and batch are mutually exclusive.

    Test purpose:
      - Cover the mutual-exclusion guard at the top of spawn_subagent,
        reached only when batch normalization succeeded.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-both",
        args={
            "task": "say hello",
            "batch": [{"task": "one"}],
        },
    )
    assert "ERROR" in body, body[:2000]
    assert "mutually exclusive" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_rejects_empty_task_without_batch(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An empty task with no batch is rejected.

    Test purpose:
      - Cover the required-task guard, which sits between the batch
        branch and the coercion block.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-notask",
        args={"task": "   "},
    )
    assert "ERROR" in body, body[:2000]
    assert "task" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_rejects_batch_json_object(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A JSON object (not array) for batch is rejected.

    Test purpose:
      - Cover _coerce_json_list's "JSON value must be an array" branch
        via _normalize_batch.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-badbatch",
        args={"task": "", "batch": '{"task": "one"}'},
    )
    assert "ERROR" in body, body[:2000]
    assert "batch" in body, body[:2000]


# ================== C. background submission + status poll =================


@pytest.mark.integration
@pytest.mark.p1
def test_spawn_background_then_check_agent_task(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A background subagent yields a task_id that can be polled.

    Test purpose:
      - Cover the background submission path
        (submit_agent_chat_task + format_background_submission_text)
        and then the real check_agent_task lookup for that very id,
        exercising format_background_status_text with a live task
        rather than an unknown one.

    Test flow:
      1. Force spawn_subagent(background=True) and capture the
         [TASK_ID: ...] emitted in the tool output.
      2. Force check_agent_task with that id in a second turn.
      3. Assert the status text echoes the same id and does not report
         it as unknown.
    """
    srv, mock_url = mock_llm
    body = _spawn(
        app_server,
        srv,
        mock_url,
        user_id="integ-spawn-bg",
        args={"task": "say hello", "background": True},
    )
    assert "TASK_ID" in body, body[:2500]
    match = re.search(r"TASK_ID: ([A-Za-z0-9._-]+)", body)
    assert match, f"no task id in output: {body[:2500]}"
    task_id = match.group(1)

    status_body = None
    for _ in range(10):
        _force(srv, "check_agent_task", {"task_id": task_id})
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
        provider_id = register_mock_provider(app_server, mock_url)
        try:
            final = _run_tool(
                app_server,
                user_id="integ-spawn-bg-check",
                prompt=f"{_PARENT_MARKER} check the background task",
            )
            status_body = _body(final)
        finally:
            srv.force_tool_call = False
            unregister_mock_provider(app_server, provider_id)
        if task_id in status_body:
            break
        time.sleep(1.0)

    assert status_body is not None
    assert task_id in status_body, (
        f"status text lost the task id; logs="
        f"{app_server.logs_tail()[-2000:]}"
    )
    assert "not found" not in status_body.lower(), status_body[:2500]


@pytest.mark.integration
@pytest.mark.p2
def test_check_agent_task_empty_id_rejected(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A blank task_id is rejected before any lookup.

    Test purpose:
      - Cover check_agent_task's normalize_id guard.
    """
    srv, mock_url = mock_llm
    _force(srv, "check_agent_task", {"task_id": "  "})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-check-emptyid",
            prompt=f"{_PARENT_MARKER} check an empty task id",
        )
        body = _body(final)
        assert "ERROR" in body, body[:2000]
        assert "task_id" in body, body[:2000]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)

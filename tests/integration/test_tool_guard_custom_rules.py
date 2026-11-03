# -*- coding: utf-8 -*-
"""Custom tool-guard rule matching through real tool calls.

Covers ``security/tool_guard/guardians/rule_guardian.py``'s matching
logic by registering user-defined rules via the tool-guard config
endpoint and then driving a real ``execute_shell_command`` call: pattern
matching, ``exclude_patterns`` suppression, per-tool scoping, and the
tolerance for a malformed regex.

Every rule matches a harmless marker token (``integ_guard_token_*``)
rather than a genuinely dangerous command, so no destructive shell
command is ever issued. Findings are observed through
``GET /api/approval/list`` and each test denies its own approval so the
turn does not linger.

API endpoints:
  - GET  /api/config/security/tool-guard
  - PUT  /api/config/security/tool-guard
  - POST /api/console/chat/task
  - GET  /api/approval/list
  - POST /api/approval/deny
"""
from __future__ import annotations

import json
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

_HTTP_TIMEOUT = default_http_timeout(30.0)


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


@pytest.fixture
def guard_baseline(app_server):
    """Snapshot the tool-guard config and restore it afterwards."""
    resp = app_server.api_request(
        "GET",
        "/api/config/security/tool-guard",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    baseline = resp.json()
    yield baseline
    app_server.api_request(
        "PUT",
        "/api/config/security/tool-guard",
        json=baseline,
        timeout=_HTTP_TIMEOUT,
    )


def _install_rule(app_server, baseline: dict, rule: dict) -> None:
    """Add one custom rule on top of the snapshot config."""
    patched = dict(baseline)
    patched["enabled"] = True
    patched["custom_rules"] = list(baseline.get("custom_rules") or []) + [rule]
    resp = app_server.api_request(
        "PUT",
        "/api/config/security/tool-guard",
        json=patched,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def _run_shell(app_server, srv, mock_url, *, command: str, user_id: str):
    """Force one shell tool call under SMART approval; return session id."""
    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps({"command": command})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    session_id = f"console:{user_id}"
    submit = app_server.api_request(
        "POST",
        "/api/console/chat/task",
        json={
            "channel": "console",
            "user_id": user_id,
            "session_id": session_id,
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "text", "text": "run it"}],
                },
            ],
            "request_context": {"approval_level": "smart"},
        },
        timeout=default_http_timeout(60.0),
    )
    assert submit.status_code == 200, app_server.logs_tail()[-2000:]
    return session_id, provider_id, submit.json()["task_id"]


def _wait_for_approval(app_server, session_id: str, timeout: float = 30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = app_server.api_request(
            "GET",
            "/api/approval/list",
            params={"session_id": session_id},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            items = resp.json().get("pending_approvals") or []
            if items:
                return items[0]
        time.sleep(0.5)
    return None


def _wait_finished(app_server, task_id: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        poll = app_server.api_request(
            "GET",
            f"/api/console/chat/task/{task_id}",
            timeout=_HTTP_TIMEOUT,
        )
        if poll.status_code == 200 and poll.json().get("status") == "finished":
            return True
        time.sleep(0.4)
    return False


def _deny(app_server, approval: dict, session_id: str) -> None:
    try:
        app_server.api_request(
            "POST",
            "/api/approval/deny",
            json={
                "request_id": approval.get("request_id"),
                "session_id": approval.get("root_session_id") or session_id,
            },
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 - cleanup must not mask failures
        pass


# ============================== A. matching ================================


@pytest.mark.integration
@pytest.mark.p1
def test_custom_rule_matches_marker_token(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    guard_baseline,  # pylint: disable=redefined-outer-name
):
    """A custom rule flags a command containing its marker token.

    Test purpose:
      - Cover GuardRule pattern compilation and
        RuleBasedToolGuardian.guard's match path with a rule the test
        owns, using a harmless ``echo`` payload so nothing destructive
        runs.

    Test flow:
      1. Install a rule matching ``integ_guard_token_hit``.
      2. Force ``echo integ_guard_token_hit``.
      3. Assert an approval carrying the rule's description appears.
    """
    srv, mock_url = mock_llm
    _install_rule(
        app_server,
        guard_baseline,
        {
            "id": "INTEG_RULE_HIT",
            "tools": ["execute_shell_command"],
            "params": ["command"],
            "category": "command_injection",
            "severity": "HIGH",
            "patterns": [r"\binteg_guard_token_hit\b"],
            "exclude_patterns": [],
            "description": "integ marker token detected",
            "remediation": "remove the marker",
        },
    )
    session_id, provider_id, _task = _run_shell(
        app_server,
        srv,
        mock_url,
        command="echo integ_guard_token_hit",
        user_id="integ-rule-hit",
    )
    approval = None
    try:
        approval = _wait_for_approval(app_server, session_id)
        assert approval is not None, (
            "custom rule did not raise an approval; "
            f"logs={app_server.logs_tail()[-2500:]}"
        )
        blob = json.dumps(approval, ensure_ascii=False)
        assert "integ marker token detected" in blob, blob[:1500]
    finally:
        if approval:
            _deny(app_server, approval, session_id)
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_exclude_pattern_suppresses_match(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    guard_baseline,  # pylint: disable=redefined-outer-name
):
    """An exclude_patterns hit suppresses an otherwise matching rule.

    Test purpose:
      - Cover the exclude-pattern branch of GuardRule: the command
        matches the rule's pattern *and* its exclusion, so no approval
        may be raised and the turn must complete on its own.

    Test flow:
      1. Install a rule matching ``integ_guard_token_skip`` but
         excluding commands containing ``integ_allowlisted``.
      2. Force a command containing both tokens.
      3. Assert the turn finishes with no pending approval.
    """
    srv, mock_url = mock_llm
    _install_rule(
        app_server,
        guard_baseline,
        {
            "id": "INTEG_RULE_EXCLUDED",
            "tools": ["execute_shell_command"],
            "params": ["command"],
            "category": "command_injection",
            "severity": "HIGH",
            "patterns": [r"\binteg_guard_token_skip\b"],
            "exclude_patterns": [r"\binteg_allowlisted\b"],
            "description": "integ excluded token",
            "remediation": "n/a",
        },
    )
    session_id, provider_id, task_id = _run_shell(
        app_server,
        srv,
        mock_url,
        command="echo integ_guard_token_skip integ_allowlisted",
        user_id="integ-rule-excluded",
    )
    try:
        assert _wait_finished(app_server, task_id), (
            "excluded command still gated the turn; "
            f"logs={app_server.logs_tail()[-2500:]}"
        )
        listing = app_server.api_request(
            "GET",
            "/api/approval/list",
            params={"session_id": session_id},
            timeout=_HTTP_TIMEOUT,
        )
        assert listing.status_code == 200, listing.text
        assert not (listing.json().get("pending_approvals") or []), (
            "exclude_patterns did not suppress the finding: "
            + listing.text[:1200]
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_rule_scoped_to_other_tool_does_not_fire(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    guard_baseline,  # pylint: disable=redefined-outer-name
):
    """A rule scoped to a different tool ignores this call.

    Test purpose:
      - Cover the per-tool scoping check: the pattern would match, but
        the rule targets ``read_file``, so a shell call must pass.
    """
    srv, mock_url = mock_llm
    _install_rule(
        app_server,
        guard_baseline,
        {
            "id": "INTEG_RULE_OTHER_TOOL",
            "tools": ["read_file"],
            "params": ["file_path"],
            "category": "command_injection",
            "severity": "HIGH",
            "patterns": [r"\binteg_guard_token_scoped\b"],
            "exclude_patterns": [],
            "description": "integ scoped to read_file",
            "remediation": "n/a",
        },
    )
    _session, provider_id, task_id = _run_shell(
        app_server,
        srv,
        mock_url,
        command="echo integ_guard_token_scoped",
        user_id="integ-rule-scoped",
    )
    try:
        assert _wait_finished(app_server, task_id), (
            "a rule scoped to another tool gated this call; "
            f"logs={app_server.logs_tail()[-2500:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_malformed_rule_regex_is_tolerated(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    guard_baseline,  # pylint: disable=redefined-outer-name
):
    """A rule with a broken regex does not break tool execution.

    Test purpose:
      - Cover GuardRule's re.error handling: an unparseable pattern is
        logged and skipped, so a normal command must still run instead
        of the guard raising into the turn.
    """
    srv, mock_url = mock_llm
    _install_rule(
        app_server,
        guard_baseline,
        {
            "id": "INTEG_RULE_BAD_REGEX",
            "tools": ["execute_shell_command"],
            "params": ["command"],
            "category": "command_injection",
            "severity": "HIGH",
            "patterns": ["integ_unclosed("],
            "exclude_patterns": [],
            "description": "integ malformed pattern",
            "remediation": "n/a",
        },
    )
    _session, provider_id, task_id = _run_shell(
        app_server,
        srv,
        mock_url,
        command="echo integ_plain_output",
        user_id="integ-rule-badregex",
    )
    try:
        assert _wait_finished(app_server, task_id), (
            "a malformed guard rule blocked execution; "
            f"logs={app_server.logs_tail()[-2500:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)

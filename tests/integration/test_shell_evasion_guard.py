# -*- coding: utf-8 -*-
"""Shell-evasion guardian detectors driven through real agent turns.

Covers ``security/tool_guard/guardians/shell_evasion_guardian.py``.
Every detector there is disabled by default, so each test enables the
specific check via ``PUT /api/config/security/tool-guard`` (which also
exercises the guardian ``reload()`` path), then drives a real
``execute_shell_command`` tool call whose ``command`` should trip it.

Findings are asserted through ``GET /api/approval/list``: the guard
raises an approval whose ``result_summary`` carries the finding
descriptions, so a matched detector is observable over HTTP rather than
inferred from logs.  Each test denies its own approval so the turn does
not linger.

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
def tool_guard_baseline(app_server):
    """Snapshot the tool-guard config and restore it afterwards."""
    resp = app_server.api_request(
        "GET",
        "/api/config/security/tool-guard",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()[-2000:]
    baseline = resp.json()
    yield baseline
    app_server.api_request(
        "PUT",
        "/api/config/security/tool-guard",
        json=baseline,
        timeout=_HTTP_TIMEOUT,
    )


def _enable_check(app_server, baseline: dict, check_name: str) -> None:
    """Turn on one shell-evasion check, leaving the rest untouched."""
    patched = dict(baseline)
    patched["enabled"] = True
    checks = dict(baseline.get("shell_evasion_checks") or {})
    checks[check_name] = True
    patched["shell_evasion_checks"] = checks
    resp = app_server.api_request(
        "PUT",
        "/api/config/security/tool-guard",
        json=patched,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()[-2000:]
    after = app_server.api_request(
        "GET",
        "/api/config/security/tool-guard",
        timeout=_HTTP_TIMEOUT,
    )
    assert (
        after.json().get("shell_evasion_checks", {}).get(check_name) is True
    ), after.json().get("shell_evasion_checks")


def _submit_shell_turn(app_server, *, user_id: str) -> str:
    """Start a chat task that will issue the forced shell tool call."""
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
                    "content": [{"type": "text", "text": "run it"}],
                },
            ],
            # SMART surfaces MEDIUM+ findings as an approval request.
            "request_context": {"approval_level": "smart"},
        },
        timeout=default_http_timeout(60.0),
    )
    assert submit.status_code == 200, app_server.logs_tail()[-2000:]
    return submit.json()["task_id"]


def _wait_for_approval(app_server, session_id: str, timeout: float = 40.0):
    """Poll the approval list for this session; return the entry or None."""
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


def _deny(app_server, request_id: str) -> None:
    """Release a pending approval so the agent turn can finish."""
    try:
        app_server.api_request(
            "POST",
            "/api/approval/deny",
            json={"request_id": request_id},
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 - cleanup must not mask failures
        pass


def _assert_detector_fires(
    app_server,
    srv,
    mock_url,
    baseline: dict,
    *,
    check_name: str,
    command: str,
    user_id: str,
    expect_in_summary: str,
) -> None:
    """Enable one check, run the command, assert the finding surfaced."""
    _enable_check(app_server, baseline, check_name)
    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps({"command": command})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    approval = None
    try:
        _submit_shell_turn(app_server, user_id=user_id)
        approval = _wait_for_approval(app_server, f"console:{user_id}")
        assert approval is not None, (
            f"{check_name} raised no approval for {command!r}; "
            f"logs={app_server.logs_tail()[-2500:]}"
        )
        summary = json.dumps(approval, ensure_ascii=False)
        assert (
            expect_in_summary.lower() in summary.lower()
        ), f"{check_name} finding missing from approval: {summary[:1500]}"
        # exact_target is the command the guard actually inspected; the
        # displayed tool_name is the policy label ("Bash"), not the
        # tool function name.
        assert approval.get("exact_target") == command, approval
    finally:
        if approval:
            _deny(app_server, approval.get("request_id", ""))
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


# ========================= individual detectors ===========================


@pytest.mark.integration
@pytest.mark.p1
def test_backtick_command_substitution_is_flagged(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    tool_guard_baseline,  # pylint: disable=redefined-outer-name
):
    """A backtick substitution trips the command_substitution check.

    Test purpose:
      - Cover _check_command_substitution's quote-aware backtick scan,
        which walks the command with _QuoteState rather than a regex.
    """
    srv, mock_url = mock_llm
    _assert_detector_fires(
        app_server,
        srv,
        mock_url,
        tool_guard_baseline,
        check_name="command_substitution",
        command="echo `whoami`",
        user_id="integ-evasion-backtick",
        expect_in_summary="substitution",
    )


@pytest.mark.integration
@pytest.mark.p2
def test_dollar_paren_substitution_is_flagged(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    tool_guard_baseline,  # pylint: disable=redefined-outer-name
):
    """A $(...) substitution trips the same check via its patterns.

    Test purpose:
      - Cover the _COMMAND_SUBSTITUTION_PATTERNS loop, which runs on
        the content outside single quotes (a separate branch from the
        backtick walk).
    """
    srv, mock_url = mock_llm
    _assert_detector_fires(
        app_server,
        srv,
        mock_url,
        tool_guard_baseline,
        check_name="command_substitution",
        command="echo $(whoami)",
        user_id="integ-evasion-dollarparen",
        expect_in_summary="substitution",
    )


@pytest.mark.integration
@pytest.mark.p1
def test_ansi_c_quoting_is_flagged(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    tool_guard_baseline,  # pylint: disable=redefined-outer-name
):
    """ANSI-C quoting ($'...') trips the obfuscated_flags check.

    Test purpose:
      - Cover _check_obfuscated_flags' _ANSI_C_QUOTE_RE branch, which
        exists because ``$'\\x2d exec'`` can hide a flag from
        regex-based rules.
    """
    srv, mock_url = mock_llm
    _assert_detector_fires(
        app_server,
        srv,
        mock_url,
        tool_guard_baseline,
        check_name="obfuscated_flags",
        command="echo $'\\x2dn' hello",
        user_id="integ-evasion-ansic",
        expect_in_summary="quoting",
    )


@pytest.mark.integration
@pytest.mark.p2
def test_backslash_escaped_whitespace_is_flagged(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    tool_guard_baseline,  # pylint: disable=redefined-outer-name
):
    """Backslash-escaped whitespace trips its own check.

    Test purpose:
      - Cover _check_backslash_escaped_whitespace, which catches
        ``r\\m`` style splitting of a command name.
    """
    srv, mock_url = mock_llm
    _assert_detector_fires(
        app_server,
        srv,
        mock_url,
        tool_guard_baseline,
        check_name="backslash_escaped_whitespace",
        command="ec\\ ho hello",
        user_id="integ-evasion-bswhite",
        expect_in_summary="escap",
    )


@pytest.mark.integration
@pytest.mark.p2
def test_hidden_newline_is_flagged(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    tool_guard_baseline,  # pylint: disable=redefined-outer-name
):
    """An embedded newline trips the newlines check.

    Test purpose:
      - Cover _check_newlines, including its heredoc exemption path
        (_looks_like_heredoc returns False here, so the finding fires).
    """
    srv, mock_url = mock_llm
    _assert_detector_fires(
        app_server,
        srv,
        mock_url,
        tool_guard_baseline,
        check_name="newlines",
        command="echo one\necho two",
        user_id="integ-evasion-newline",
        expect_in_summary="newline",
    )


@pytest.mark.integration
@pytest.mark.p2
def test_comment_quote_desync_is_flagged(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    tool_guard_baseline,  # pylint: disable=redefined-outer-name
):
    """An unbalanced quote after a comment trips its check.

    Test purpose:
      - Cover _check_comment_quote_desync, which detects a ``#``
        comment that leaves quote state unbalanced.
    """
    srv, mock_url = mock_llm
    _assert_detector_fires(
        app_server,
        srv,
        mock_url,
        tool_guard_baseline,
        check_name="comment_quote_desync",
        command="echo ok # trailing 'unclosed",
        user_id="integ-evasion-desync",
        expect_in_summary="quote",
    )


# ===================== negative control / disabled state ==================


@pytest.mark.integration
@pytest.mark.p1
def test_benign_command_raises_no_approval(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    tool_guard_baseline,  # pylint: disable=redefined-outer-name
):
    """With detectors on, a clean command is not flagged.

    Test purpose:
      - Negative control for the detector tests above: it proves the
        approvals they observe come from the specific evasion pattern
        and not from merely enabling the guard.

    Test flow:
      1. Enable command_substitution.
      2. Run a plain ``echo hello``.
      3. Assert the turn finishes with no pending approval.
    """
    srv, mock_url = mock_llm
    _enable_check(app_server, tool_guard_baseline, "command_substitution")
    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps({"command": "echo hello"})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    user_id = "integ-evasion-benign"
    try:
        task_id = _submit_shell_turn(app_server, user_id=user_id)
        deadline = time.time() + 60.0
        finished = False
        while time.time() < deadline:
            poll = app_server.api_request(
                "GET",
                f"/api/console/chat/task/{task_id}",
                timeout=_HTTP_TIMEOUT,
            )
            if poll.json().get("status") == "finished":
                finished = True
                break
            time.sleep(0.4)
        assert finished, (
            "benign command did not finish (unexpected approval wait?); "
            f"logs={app_server.logs_tail()[-2500:]}"
        )
        listing = app_server.api_request(
            "GET",
            "/api/approval/list",
            params={"session_id": f"console:{user_id}"},
            timeout=_HTTP_TIMEOUT,
        )
        assert listing.status_code == 200, listing.text
        assert not (listing.json().get("pending_approvals") or []), (
            "benign command raised an approval: " + listing.text[:1500]
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_disabled_check_does_not_fire(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    tool_guard_baseline,  # pylint: disable=redefined-outer-name
):
    """A pattern whose check is off is not flagged.

    Test purpose:
      - Cover the per-check enablement gate in
        ShellEvasionGuardian.guard: with only ``newlines`` enabled, a
        backtick substitution must pass unflagged.
    """
    srv, mock_url = mock_llm
    _enable_check(app_server, tool_guard_baseline, "newlines")
    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps({"command": "echo `date`"})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    user_id = "integ-evasion-offcheck"
    try:
        task_id = _submit_shell_turn(app_server, user_id=user_id)
        deadline = time.time() + 60.0
        finished = False
        while time.time() < deadline:
            poll = app_server.api_request(
                "GET",
                f"/api/console/chat/task/{task_id}",
                timeout=_HTTP_TIMEOUT,
            )
            if poll.json().get("status") == "finished":
                finished = True
                break
            time.sleep(0.4)
        assert finished, (
            "disabled check still gated the turn; "
            f"logs={app_server.logs_tail()[-2500:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)

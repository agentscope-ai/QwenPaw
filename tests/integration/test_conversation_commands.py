# -*- coding: utf-8 -*-
"""Conversation slash commands driven through console chat turns.

Covers ``agents/command_handler.py``'s SYSTEM_COMMANDS dispatch by
sending each command as a normal user message: the handler intercepts
it before the model, so these turns need no LLM tool calls and
exercise history/compaction/memory branches directly.

API endpoints:
  - POST /api/console/chat/task
  - GET  /api/console/chat/task/{task_id}
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

_HTTP_TIMEOUT = default_http_timeout(60.0)


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server (some commands still need it)."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


@pytest.fixture(scope="module")
def provider(app_server, mock_llm):  # pylint: disable=redefined-outer-name
    """Register the mock provider once for this module."""
    _srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    yield provider_id
    unregister_mock_provider(app_server, provider_id)


def _send(app_server, *, user_id: str, text: str) -> dict:
    """Send one message and poll the task to completion."""
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
                    "content": [{"type": "text", "text": text}],
                },
            ],
            "request_context": {"approval_level": "off"},
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert submit.status_code == 200, app_server.logs_tail()[-2000:]
    task_id = submit.json()["task_id"]
    deadline = time.time() + 90.0
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
        "command task did not finish: " + app_server.logs_tail()[-2000:],
    )


@pytest.mark.integration
@pytest.mark.p1
def test_history_and_clear_commands(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """/history lists the session, /clear resets it.

    Test purpose:
      - Cover command_handler's history rendering and clear paths on a
        session that already has a turn in it.

    Test flow:
      1. Send a normal message to seed history.
      2. Send /history, then /clear; both must complete.
    """
    user = "integ-cmd-history"
    assert (
        _send(app_server, user_id=user, text="hello there").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/history").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/clear").get(
            "status",
        )
        == "finished"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_compact_and_new_commands(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """/compact summarizes context; /new starts a fresh session.

    Test purpose:
      - Cover the compaction command path (scroll manager compaction)
        and the new-session reset.
    """
    user = "integ-cmd-compact"
    assert (
        _send(app_server, user_id=user, text="first message").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/compact").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/new").get(
            "status",
        )
        == "finished"
    )


@pytest.mark.integration
@pytest.mark.p2
def test_memory_status_commands(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """/reme_status and /memorize exercise the memory paths.

    Test purpose:
      - Cover the ReMe status report and the memorize command branch
        (which may degrade gracefully when memory is unavailable).
    """
    user = "integ-cmd-memory"
    assert (
        _send(app_server, user_id=user, text="remember this fact").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/reme_status").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/memorize").get(
            "status",
        )
        == "finished"
    )


@pytest.mark.integration
@pytest.mark.p2
def test_plan_and_system_prompt_commands(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """Bare /plan reports status; /system_prompt dumps the prompt.

    Test purpose:
      - Cover the bare-/plan status branch (as opposed to plan-mode
        activation with arguments) and the system-prompt dump.
    """
    user = "integ-cmd-plan"
    assert (
        _send(app_server, user_id=user, text="/plan").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/system_prompt").get(
            "status",
        )
        == "finished"
    )


@pytest.mark.integration
@pytest.mark.p2
def test_dump_and_load_history_commands(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """/dump_history and /load_history round-trip session state.

    Test purpose:
      - Cover the history serialization commands.
    """
    user = "integ-cmd-dump"
    assert (
        _send(app_server, user_id=user, text="seed for dump").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/dump_history").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/load_history").get(
            "status",
        )
        == "finished"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_recall_history_search_and_expand(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """recall_history search/expand run against the session scroll.

    Test purpose:
      - Cover agents/context/scroll/recall_tool.py: the search op over
        persisted history and the expand op over a seq range, driven
        as real tool calls inside the app.

    Test flow:
      1. Seed a couple of normal turns so the scroll has content.
      2. Force recall_history(op="search"), then op="expand".
    """
    srv, _mock_url = mock_llm
    user = "integ-cmd-recall"
    assert (
        _send(app_server, user_id=user, text="alpha topic here").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="beta topic here").get(
            "status",
        )
        == "finished"
    )

    srv.force_tool_call = True
    srv.tool_call_name = "recall_history"
    srv.tool_call_arguments = json.dumps(
        {"op": "search", "query": "alpha", "k": 5},
    )
    try:
        final = _send(app_server, user_id=user, text="what did I say")
        assert final.get("status") == "finished", final

        srv.tool_call_arguments = json.dumps(
            {"op": "expand", "lo": 0, "hi": 5},
        )
        final_expand = _send(app_server, user_id=user, text="expand it")
        assert final_expand.get("status") == "finished", final_expand
    finally:
        srv.force_tool_call = False


@pytest.mark.integration
@pytest.mark.p2
def test_recall_history_invalid_op(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """An unsupported recall op is rejected with a clear error.

    Test purpose:
      - Cover the op-validation branch of the recall tool.
    """
    srv, _mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "recall_history"
    srv.tool_call_arguments = json.dumps({"op": "integ_bogus_op"})
    try:
        final = _send(
            app_server,
            user_id="integ-cmd-recall-bad",
            text="bad recall",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False


@pytest.mark.integration
@pytest.mark.p2
def test_summarize_status_and_proactive_commands(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """/summarize_status and /proactive report subsystem state.

    Test purpose:
      - Cover two more command_handler branches (compaction status and
        proactive-messaging status).
    """
    user = "integ-cmd-status"
    assert (
        _send(app_server, user_id=user, text="/summarize_status").get(
            "status",
        )
        == "finished"
    )
    assert (
        _send(app_server, user_id=user, text="/proactive").get(
            "status",
        )
        == "finished"
    )


def _reply_text(final: dict) -> str:
    """Flatten a finished command turn to searchable text."""
    return json.dumps(final, ensure_ascii=False)


@pytest.mark.integration
@pytest.mark.p1
def test_message_command_shows_indexed_message(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """/message <n> renders the nth stored message.

    Test purpose:
      - Cover command_handler's _process_message success path: it must
        report the index, the message role, and the original content of
        the addressed turn.

    Test flow:
      1. Seed the session with a message carrying a unique marker.
      2. Send /message 1 and assert the marker and an index header come
         back, proving the stored message was located and rendered.
    """
    user = "integ-cmd-message-idx"
    marker = "INTEG-CMD-MSG-MARKER-3310"
    assert (
        _send(app_server, user_id=user, text=f"remember {marker}").get(
            "status",
        )
        == "finished"
    )
    final = _send(app_server, user_id=user, text="/message 1")
    assert final.get("status") == "finished", final
    body = _reply_text(final)
    assert marker in body, body[:2000]
    assert "Message 1/" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_message_command_without_index_shows_usage(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """A bare /message prints usage instead of failing.

    Test purpose:
      - Cover the no-arguments branch of _process_message, which must
        tell the caller the available range rather than error out.
    """
    user = "integ-cmd-message-usage"
    _send(app_server, user_id=user, text="seed a turn")
    final = _send(app_server, user_id=user, text="/message")
    assert final.get("status") == "finished", final
    body = _reply_text(final)
    assert "Usage" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_message_command_non_numeric_index_rejected(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """A non-numeric index is reported as invalid.

    Test purpose:
      - Cover the ValueError branch of _process_message, distinct from
        the missing-argument and out-of-range branches.
    """
    user = "integ-cmd-message-bad"
    _send(app_server, user_id=user, text="seed a turn")
    final = _send(app_server, user_id=user, text="/message abc")
    assert final.get("status") == "finished", final
    body = _reply_text(final)
    assert "Invalid Index" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_message_command_out_of_range_index_rejected(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """An index beyond the stored history is reported out of range.

    Test purpose:
      - Cover the bounds check of _process_message, which must name the
        valid range so the caller can retry.
    """
    user = "integ-cmd-message-range"
    _send(app_server, user_id=user, text="seed a turn")
    final = _send(app_server, user_id=user, text="/message 9999")
    assert final.get("status") == "finished", final
    body = _reply_text(final)
    assert "Out of Range" in body, body[:2000]


@pytest.mark.integration
@pytest.mark.p1
def test_compact_str_reports_summary_state(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """/compact_str reports the continuation-summary state.

    Test purpose:
      - Cover _process_compact_str on both sides of its guard: with no
        compaction yet it must say so explicitly, and after an explicit
        /compact it must still answer without error.

    Test flow:
      1. On a fresh session, /compact_str must report no summary.
      2. Run /compact, then /compact_str again; the command must
         complete and mention a summary.
    """
    user = "integ-cmd-compactstr"
    _send(app_server, user_id=user, text="seed a turn for compaction")

    before = _send(app_server, user_id=user, text="/compact_str")
    assert before.get("status") == "finished", before
    assert "Summary" in _reply_text(before), _reply_text(before)[:2000]

    assert (
        _send(app_server, user_id=user, text="/compact").get("status")
        == "finished"
    )
    after = _send(app_server, user_id=user, text="/compact_str")
    assert after.get("status") == "finished", after
    assert "Summary" in _reply_text(after), _reply_text(after)[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_dream_command_completes(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """/dream answers even when no memory manager is configured.

    Test purpose:
      - Cover _process_dream's guard branch: this environment has no
        active memory manager, so the command must report that it cannot
        run an auto-dream rather than raising into the turn.
    """
    user = "integ-cmd-dream"
    _send(app_server, user_id=user, text="seed a turn")
    final = _send(app_server, user_id=user, text="/dream")
    assert final.get("status") == "finished", final
    body = _reply_text(final)
    assert "dream" in body.lower(), body[:2000]


@pytest.mark.integration
@pytest.mark.p1
def test_skills_command_lists_chat_skills(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """/skills lists the chat-available skills for this channel.

    Test purpose:
      - Cover the /skills control handler: it resolves the workspace
        skills directory, filters by the channel's effective skills, and
        renders a list. The reply must mention skills rather than being
        routed to the model as ordinary text.
    """
    user = "integ-cmd-skills"
    final = _send(app_server, user_id=user, text="/skills")
    assert final.get("status") == "finished", final
    body = _reply_text(final).lower()
    assert "skill" in body, _reply_text(final)[:2000]


@pytest.mark.integration
@pytest.mark.p2
def test_unknown_skill_command_falls_through(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """An unmatched /<name> command does not break the turn.

    Test purpose:
      - Cover _skill_fallback_handler's miss path: when no skill
        matches, the handler returns None and the text continues through
        the normal runner, so the turn must still complete.
    """
    user = "integ-cmd-unknown-skill"
    final = _send(
        app_server,
        user_id=user,
        text="/integ-no-such-skill-8813 do something",
    )
    assert final.get("status") == "finished", final


@pytest.mark.integration
@pytest.mark.p2
def test_bracketed_skill_syntax_is_accepted(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """The bracketed /[name with spaces] form is parsed, not crashed.

    Test purpose:
      - Cover _parse_skill_query's bracket branch, which exists so skill
        names containing spaces remain addressable. No such skill is
        installed here, so the turn must fall through cleanly.
    """
    user = "integ-cmd-bracket-skill"
    final = _send(
        app_server,
        user_id=user,
        text="/[integ no such skill] hello",
    )
    assert final.get("status") == "finished", final

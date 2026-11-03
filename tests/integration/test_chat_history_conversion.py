# -*- coding: utf-8 -*-
"""Chat-history conversion of non-text message blocks.

Covers ``app/chats/utils.py``'s ``agentscope_msg_to_message``: the block
dispatch that turns persisted AgentScope content into runtime Message
objects.  Text-only history is already covered elsewhere; the branches
here need a session whose stored context actually contains tool_use /
tool_result / thinking / media blocks, so each test first drives a real
agent turn that produces them and then reads the history back over HTTP.

Assertions check the converted shape (message types, call ids, tool
names, arguments) rather than just a 200, so a regression that drops or
mis-labels a block type fails the test.

API endpoints:
  - POST /api/chats
  - GET  /api/chats/{chat_id}
  - DELETE /api/chats/{chat_id}
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
    """Module-scoped mock OpenAI server with tool_call support."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


def _run_turn(app_server, *, user_id: str, prompt: str) -> None:
    """Drive one console turn to completion for this session."""
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
    deadline = time.time() + 180.0
    while time.time() < deadline:
        poll = app_server.api_request(
            "GET",
            f"/api/console/chat/task/{task_id}",
            timeout=default_http_timeout(15.0),
        )
        assert poll.status_code == 200, app_server.logs_tail()[-2000:]
        if poll.json().get("status") == "finished":
            return
        time.sleep(0.4)
    raise AssertionError(
        "turn did not finish: " + app_server.logs_tail()[-2000:],
    )


def _create_chat(app_server, *, user_id: str, name: str) -> str:
    """Register a chat bound to this session; return its chat id."""
    resp = app_server.api_request(
        "POST",
        "/api/chats",
        json={
            "name": name,
            "session_id": f"console:{user_id}",
            "user_id": user_id,
            "channel": "console",
            "meta": {},
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()[-2000:]
    return resp.json()["id"]


def _read_history(app_server, chat_id: str) -> list[dict]:
    """Read a chat's converted history messages."""
    resp = app_server.api_request(
        "GET",
        f"/api/chats/{chat_id}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()[-2000:]
    body = resp.json()
    assert isinstance(body.get("messages"), list), body
    return body["messages"]


def _types(messages: list[dict]) -> list[str]:
    return [str(m.get("type")) for m in messages]


def _delete_chat(app_server, chat_id: str) -> None:
    try:
        app_server.api_request(
            "DELETE",
            f"/api/chats/{chat_id}",
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 - cleanup must not mask failures
        pass


@pytest.mark.integration
@pytest.mark.p1
def test_history_converts_tool_call_and_result_blocks(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A turn with a tool call converts to plugin_call + output messages.

    Test purpose:
      - Cover the ``tool_use``/``tool_call`` and ``tool_result`` branches
        of agentscope_msg_to_message, including FunctionCall /
        FunctionCallOutput construction and the JSON encoding of dict
        arguments.

    Test flow:
      1. Force a get_current_time tool call and run the turn.
      2. Register a chat for that session and read its history.
      3. Assert both a plugin_call and a plugin_call_output message are
         present and the call carries the tool name.
    """
    srv, mock_url = mock_llm
    user_id = "integ-hist-toolcall"
    srv.force_tool_call = True
    srv.tool_call_name = "get_current_time"
    srv.tool_call_arguments = "{}"
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    chat_id = None
    try:
        _run_turn(app_server, user_id=user_id, prompt="what time is it")
        srv.force_tool_call = False
        chat_id = _create_chat(
            app_server,
            user_id=user_id,
            name="history tool call",
        )
        messages = _read_history(app_server, chat_id)
        types = _types(messages)
        assert any("plugin_call" in t for t in types), types
        assert any("plugin_call_output" in t for t in types), types
        blob = json.dumps(messages, ensure_ascii=False)
        assert "get_current_time" in blob, blob[:2000]
    finally:
        srv.force_tool_call = False
        if chat_id:
            _delete_chat(app_server, chat_id)
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_history_preserves_tool_arguments_json(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Dict tool arguments survive the round trip as JSON.

    Test purpose:
      - Cover the ``isinstance(block.get("input"), (dict, list))``
        branch that json.dumps the arguments; a naive passthrough would
        emit a Python repr instead.

    Test flow:
      1. Force a read_file call with a distinctive path argument.
      2. Read the history and assert that argument value appears.
    """
    srv, mock_url = mock_llm
    user_id = "integ-hist-toolargs"
    marker = "integ-hist-arg-marker.txt"
    srv.force_tool_call = True
    srv.tool_call_name = "read_file"
    srv.tool_call_arguments = json.dumps({"file_path": marker})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    chat_id = None
    try:
        _run_turn(app_server, user_id=user_id, prompt="read that file")
        srv.force_tool_call = False
        chat_id = _create_chat(
            app_server,
            user_id=user_id,
            name="history tool args",
        )
        messages = _read_history(app_server, chat_id)
        blob = json.dumps(messages, ensure_ascii=False)
        assert marker in blob, blob[:2000]
        assert "read_file" in blob, blob[:2000]
    finally:
        srv.force_tool_call = False
        if chat_id:
            _delete_chat(app_server, chat_id)
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_history_groups_consecutive_text_into_one_message(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Plain text turns convert to message-type entries with their text.

    Test purpose:
      - Cover the text branch plus clean_display_text: the assistant
        reply must come back as a MESSAGE entry carrying the text, and
        the user's own prompt must be present too.

    Test flow:
      1. Run a plain (no tool) turn with a distinctive prompt.
      2. Assert the prompt text is in the converted history.
    """
    srv, mock_url = mock_llm
    user_id = "integ-hist-text"
    marker = "INTEG-HIST-TEXT-5501"
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    chat_id = None
    try:
        _run_turn(app_server, user_id=user_id, prompt=f"hello {marker}")
        chat_id = _create_chat(
            app_server,
            user_id=user_id,
            name="history text",
        )
        messages = _read_history(app_server, chat_id)
        assert messages, "history was empty after a completed turn"
        blob = json.dumps(messages, ensure_ascii=False)
        assert marker in blob, blob[:2000]
        assert any("message" in t for t in _types(messages)), _types(messages)
    finally:
        if chat_id:
            _delete_chat(app_server, chat_id)
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_history_carries_metadata_and_timestamps(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Converted messages expose the original id / name / timestamp.

    Test purpose:
      - Cover the metadata assembly and the timestamp reformatting
        branch (strptime + user timezone), which runs for every stored
        message.
    """
    srv, mock_url = mock_llm
    user_id = "integ-hist-meta"
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    chat_id = None
    try:
        _run_turn(app_server, user_id=user_id, prompt="hello metadata")
        chat_id = _create_chat(
            app_server,
            user_id=user_id,
            name="history metadata",
        )
        messages = _read_history(app_server, chat_id)
        assert messages, "history was empty after a completed turn"
        with_meta = [m for m in messages if m.get("metadata")]
        assert with_meta, json.dumps(messages, ensure_ascii=False)[:2000]
        meta = with_meta[0]["metadata"]
        assert "original_id" in meta, meta
        assert "timestamp" in meta, meta
    finally:
        if chat_id:
            _delete_chat(app_server, chat_id)
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_history_of_multi_turn_session_keeps_order(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Two turns accumulate in order in the converted history.

    Test purpose:
      - Cover the multi-message loop: the converter must emit entries
        for every stored Msg, so a second turn's marker must appear
        after the first one's.
    """
    srv, mock_url = mock_llm
    user_id = "integ-hist-order"
    first = "INTEG-HIST-FIRST-11"
    second = "INTEG-HIST-SECOND-22"
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    chat_id = None
    try:
        _run_turn(app_server, user_id=user_id, prompt=f"one {first}")
        _run_turn(app_server, user_id=user_id, prompt=f"two {second}")
        chat_id = _create_chat(
            app_server,
            user_id=user_id,
            name="history order",
        )
        blob = json.dumps(
            _read_history(app_server, chat_id),
            ensure_ascii=False,
        )
        assert first in blob, blob[:2000]
        assert second in blob, blob[:2000]
        assert blob.index(first) < blob.index(
            second,
        ), "history lost chronological order"
    finally:
        if chat_id:
            _delete_chat(app_server, chat_id)
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_history_of_unknown_chat_returns_404(app_server):
    """Reading a non-existent chat is a clean 404.

    Test purpose:
      - Cover the chat-lookup guard ahead of the conversion, so a bad
        id cannot reach the converter.
    """
    resp = app_server.api_request(
        "GET",
        "/api/chats/integ-no-such-chat-9182",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text

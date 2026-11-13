# -*- coding: utf-8 -*-
"""Regression test for issue #6131.

After the 2.x migration, sending a message in an existing chat did not
refresh ``ChatSpec.updated_at``. The console session list sorts by
``updated_at`` (descending) and polls the backend, so a stale timestamp
meant the chat never re-surfaced as the most recent conversation.

The fix touches ``updated_at`` inside the console channel's ``stream_one``
executor (which serves the web-streaming, background-task and terminal
paths) and inside ``BaseChannel._consume_with_tracker`` (all other
channels). This test exercises the console web-streaming path end to end
and asserts that a second message advances ``updated_at`` past the first.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from http.server import HTTPServer

import httpx
import pytest

from tests.integration.helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    default_http_timeout,
    register_mock_provider,
    unregister_mock_provider,
)

_HTTP_TIMEOUT = default_http_timeout(15.0)


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI streaming server."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


def _drain_console_chat(app_server, session_id: str, user_id: str) -> None:
    """POST /api/console/chat and fully consume the SSE stream.

    Draining to completion guarantees the background producer (which runs
    ``stream_one``) has finished, so the ``updated_at`` touch is persisted.
    """
    body = {
        "channel": "console",
        "user_id": user_id,
        "session_id": session_id,
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [{"type": "text", "text": "hello"}],
            },
        ],
    }
    url = f"{app_server.base_url}/api/console/chat"
    with app_server.client.stream(
        "POST",
        url,
        json=body,
        timeout=httpx.Timeout(20.0, read=20.0),
    ) as resp:
        assert resp.status_code == 200, app_server.logs_tail()
        for _ in resp.iter_lines():
            pass


def _get_chat_updated_at(app_server, session_id: str, user_id: str):
    """Return (updated_at, created_at) datetimes for the target chat."""
    resp = app_server.api_request(
        "GET",
        "/api/chats",
        params={"user_id": user_id},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    matches = [c for c in resp.json() if c.get("session_id") == session_id]
    assert matches, f"chat for session {session_id} not found: {resp.json()}"
    spec = matches[0]
    updated = datetime.fromisoformat(spec["updated_at"])
    created = datetime.fromisoformat(spec["created_at"])
    return updated, created


@pytest.mark.integration
@pytest.mark.p1
def test_console_chat_second_message_advances_updated_at(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """A follow-up message must push ``updated_at`` forward (issue #6131).

    API endpoints:
    - POST /api/console/chat
    - GET  /api/chats
    """
    _srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    user_id = "integ-updated-at-6131"
    session_id = f"console:{user_id}"
    try:
        # First message creates the chat and processes a turn.
        _drain_console_chat(app_server, session_id, user_id)
        updated_1, created = _get_chat_updated_at(
            app_server,
            session_id,
            user_id,
        )
        assert updated_1 >= created

        # Ensure a measurable gap so the comparison is unambiguous.
        time.sleep(1.2)

        # Second message must refresh updated_at to a later timestamp.
        _drain_console_chat(app_server, session_id, user_id)
        updated_2, _ = _get_chat_updated_at(app_server, session_id, user_id)

        assert updated_2 > updated_1, (
            "updated_at did not advance after the second message: "
            f"first={updated_1.isoformat()} second={updated_2.isoformat()}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)

# -*- coding: utf-8 -*-
"""End-to-end coverage for foreground and background subagents."""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import json
import threading
from http.server import HTTPServer

import httpx
import pytest

from tests.integration.helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    register_mock_provider,
    scoped,
    unregister_mock_provider,
)

_HTTP_TIMEOUT = 30.0
_FOREGROUND_CHILD = "SUBAGENT_E2E_FOREGROUND_CHILD"
_BACKGROUND_CHILD = "SUBAGENT_E2E_BACKGROUND_CHILD"


class _SubagentMockLLMHandler(MockLLMHandler):
    """Drive parent tool calls and observe child completion delivery."""

    def _stream_completion(self):
        body = self._read_body()
        messages_text = json.dumps(
            body.get("messages", []),
            ensure_ascii=False,
        )
        tools = body.get("tools", [])
        has_tool_result = any(
            message.get("role") == "tool"
            for message in body.get("messages", [])
        )

        if has_tool_result:
            if "FOREGROUND_SUBAGENT_COMPLETED" in messages_text:
                self.server.foreground_parent_result_seen.set()
            if "[TASK_ID:" in messages_text:
                self.server.background_submission_seen.set()
            if "BACKGROUND_SUBAGENT_COMPLETED" in messages_text:
                self.server.background_parent_result_seen.set()
            self._stream_text("PARENT_RECEIVED_SUBAGENT_RESULT")
            return
        if _FOREGROUND_CHILD in messages_text:
            self.server.foreground_child_seen.set()
            self._stream_text("FOREGROUND_SUBAGENT_COMPLETED")
            return
        if _BACKGROUND_CHILD in messages_text:
            self.server.background_child_seen.set()
            self._stream_text("BACKGROUND_SUBAGENT_COMPLETED")
            return
        if tools and "RUN_FOREGROUND_SUBAGENT" in messages_text:
            self.server.tool_call_name = "spawn_subagent"
            self.server.tool_call_arguments = json.dumps(
                {
                    "task": _FOREGROUND_CHILD,
                    "background": False,
                },
            )
            self._stream_tool_call()
            return
        if tools and "RUN_BACKGROUND_SUBAGENT" in messages_text:
            self.server.tool_call_name = "spawn_subagent"
            self.server.tool_call_arguments = json.dumps(
                {
                    "task": _BACKGROUND_CHILD,
                    "background": True,
                },
            )
            self._stream_tool_call()
            return

        self._stream_text("MOCK_AUXILIARY_RESPONSE")


@pytest.fixture(scope="module")
def subagent_mock_llm():
    server = HTTPServer(("127.0.0.1", 0), _SubagentMockLLMHandler)
    server.foreground_child_seen = threading.Event()
    server.foreground_parent_result_seen = threading.Event()
    server.background_child_seen = threading.Event()
    server.background_submission_seen = threading.Event()
    server.background_parent_result_seen = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _run_console_turn(app_server, prompt: str, session_id: str) -> str:
    url = f"{app_server.base_url}{scoped('default', '/console/chat')}"
    body = {
        "input": [
            {
                "content": [{"type": "text", "text": prompt}],
            },
        ],
        "user_id": f"user-{session_id}",
        "session_id": session_id,
    }
    chunks: list[str] = []
    with app_server.client.stream(
        "POST",
        url,
        json=body,
        timeout=httpx.Timeout(_HTTP_TIMEOUT, read=_HTTP_TIMEOUT),
    ) as response:
        assert response.status_code == 200, app_server.logs_tail()
        chunks.extend(response.iter_lines())
    return "\n".join(chunks)


@pytest.mark.integration
@pytest.mark.p0
def test_spawn_subagent_foreground_and_background_end_to_end(
    app_server,
    subagent_mock_llm,
) -> None:
    """Run both modes through Runtime, governance, and callback wakeup."""
    server, mock_url = subagent_mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)

    try:
        foreground_stream = _run_console_turn(
            app_server,
            "RUN_FOREGROUND_SUBAGENT",
            "spawn-e2e-foreground",
        )
        assert server.foreground_child_seen.wait(10), app_server.logs_tail()
        assert server.foreground_parent_result_seen.wait(
            10,
        ), app_server.logs_tail()
        assert "denied by policy" not in foreground_stream

        background_stream = _run_console_turn(
            app_server,
            "RUN_BACKGROUND_SUBAGENT",
            "spawn-e2e-background",
        )
        assert "denied by policy" not in background_stream
        assert server.background_submission_seen.wait(
            10,
        ), app_server.logs_tail()
        assert server.background_child_seen.wait(10), app_server.logs_tail()
        assert server.background_parent_result_seen.wait(
            20,
        ), app_server.logs_tail()
    finally:
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)

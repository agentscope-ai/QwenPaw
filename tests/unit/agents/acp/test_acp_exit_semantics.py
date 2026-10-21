# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ACP liveness and task-level error termination."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from google.genai import errors as genai_errors

from qwenpaw.agents.acp.server import (
    ACPClientDisconnected,
    QwenPawACPAgent,
    _EnvelopeTracker,
    _prompt_failure_stop_reason,
)
from qwenpaw.providers.retry_chat_model import StreamIdleTimeoutError
from qwenpaw.schemas import MessageType, RunStatus


def _provider_error(message: str) -> openai.BadRequestError:
    request = httpx.Request(
        "POST",
        "https://example.test/v1/chat/completions",
    )
    response = httpx.Response(400, request=request)
    return openai.BadRequestError(
        message,
        response=response,
        body={"error": {"message": message}},
    )


def _tool_start(call_id: str = "call-1"):
    return SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL.value,
        status=RunStatus.Completed,
        content=[
            SimpleNamespace(
                data={
                    "call_id": call_id,
                    "name": "Bash",
                    "arguments": "{}",
                },
            ),
        ],
    )


def _tool_output(call_id: str = "call-1"):
    return SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL_OUTPUT.value,
        status=RunStatus.Completed,
        content=[SimpleNamespace(data={"call_id": call_id, "output": "ok"})],
    )


def test_heartbeat_keeps_active_tool_call_alive():
    tracker = _EnvelopeTracker()
    tracker.process(_tool_start())

    updates = tracker.process(
        SimpleNamespace(object="message", type="heartbeat"),
    )

    assert len(updates) == 1
    assert updates[0].session_update == "tool_call_update"
    assert updates[0].tool_call_id == "call-1"
    assert updates[0].status == "in_progress"


def test_heartbeat_is_silent_without_active_tool():
    tracker = _EnvelopeTracker()

    assert (
        tracker.process(
            SimpleNamespace(object="message", type="heartbeat"),
        )
        == []
    )


@pytest.mark.parametrize(f"call_id", [f"call-1", None])
def test_completed_tool_stops_heartbeats(call_id):
    tracker = _EnvelopeTracker()
    tracker.process(_tool_start(call_id))
    tracker.process(_tool_output(call_id))

    assert (
        tracker.process(
            SimpleNamespace(object="message", type="heartbeat"),
        )
        == []
    )


@pytest.mark.parametrize(
    f"error",
    [
        _provider_error(f"400 data_inspection_failed: inappropriate content"),
        genai_errors.ClientError(
            400,
            {f"error": {f"message": f"inappropriate content"}},
        ),
    ],
)
def test_content_moderation_returns_refusal(error):
    assert _prompt_failure_stop_reason(error) == f"refusal"


def test_internal_error_text_is_not_content_safety():
    assert _prompt_failure_stop_reason(KeyError("moderation")) is None
    assert (
        _prompt_failure_stop_reason(
            NameError("name 'content_policy' is not defined"),
        )
        is None
    )


def test_stream_idle_timeout_is_not_normalized():
    error = StreamIdleTimeoutError("policy", 600.0)

    assert _prompt_failure_stop_reason(error) is None


def test_acp_client_disconnect_returns_end_turn():
    error = ACPClientDisconnected("ACP transport closed")

    assert _prompt_failure_stop_reason(error) == "end_turn"


def test_non_transport_connection_error_is_not_normalized():
    error = ConnectionError("database connection lost")

    assert _prompt_failure_stop_reason(error) is None


def test_generic_prompt_error_is_not_normalized():
    assert _prompt_failure_stop_reason(RuntimeError("boom")) is None


@pytest.mark.parametrize(
    (f"error", f"expected"),
    [
        (ConnectionError(f"connection closed"), ACPClientDisconnected),
        (BrokenPipeError(), ACPClientDisconnected),
        (ConnectionResetError(), ACPClientDisconnected),
        (OSError(22, f"Invalid argument"), OSError),
    ],
)
def test_send_update_wraps_transport_failure(error, expected):
    agent = QwenPawACPAgent(agent_id=f"default")
    agent.on_connect(
        SimpleNamespace(
            session_update=AsyncMock(side_effect=error),
        ),
    )

    with pytest.raises(expected) as caught:
        asyncio.run(agent._send_update(f"session", object()))
    if expected is OSError:
        assert caught.value is error

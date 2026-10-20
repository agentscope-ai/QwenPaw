# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ACP liveness and task-level error termination."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.server import (
    ACPClientDisconnected,
    QwenPawACPAgent,
    _EnvelopeTracker,
    _prompt_failure_stop_reason,
)
from qwenpaw.providers.retry_chat_model import StreamIdleTimeoutError
from qwenpaw.schemas import MessageType, RunStatus


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


def test_completed_tool_stops_heartbeats():
    tracker = _EnvelopeTracker()
    tracker.process(_tool_start())
    tracker.process(_tool_output())

    assert (
        tracker.process(
            SimpleNamespace(object="message", type="heartbeat"),
        )
        == []
    )


def test_content_moderation_returns_refusal():
    error = RuntimeError(
        "400 data_inspection_failed: inappropriate content",
    )

    assert _prompt_failure_stop_reason(error) == "refusal"


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


class _ClosedConn:
    async def session_update(self, session_id, update):
        del session_id, update
        raise ConnectionError("connection closed")


def test_send_update_wraps_transport_failure():
    agent = QwenPawACPAgent(agent_id="default")
    agent.on_connect(_ClosedConn())

    with pytest.raises(ACPClientDisconnected):
        asyncio.run(agent._send_update("session", object()))

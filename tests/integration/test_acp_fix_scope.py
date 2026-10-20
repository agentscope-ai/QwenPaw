# -*- coding: utf-8 -*-
"""Scope guards for the selective ACP failure normalization.

These tests pin the boundary of the fix: only content-safety refusals and
ACP transport disconnects may become a normal ACP response. Everything
else must keep the original JSON-RPC internal-error contract, and the
keepalive frames must stay invisible to a normal short turn.
"""

# pylint: disable=protected-access,unreachable,unused-argument

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from acp import RequestError, text_block

from qwenpaw.agents.acp import server as acp_server
from qwenpaw.agents.acp.server import (
    ACP_ERROR_META_KEY,
    ACP_KEEPALIVE_META_KEY,
    QwenPawACPAgent,
    _EnvelopeTracker,
    _prompt_failure_stop_reason,
)
from qwenpaw.providers.retry_chat_model import StreamIdleTimeoutError
from qwenpaw.schemas import MessageType, RunStatus


class _RecordingConn:
    """Record every ACP notification sent by the agent."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, object]] = []
        self.times: list[float] = []

    async def session_update(self, session_id, update) -> None:
        self.updates.append((session_id, update))
        self.times.append(time.monotonic())


class _FakeWorkspace:
    def __init__(self, stream) -> None:
        self._stream = stream

    async def stream_query(self, request):
        del request
        async for event in self._stream():
            yield event


class _DisconnectingConn:
    async def session_update(self, session_id, update) -> None:
        del session_id, update
        raise ConnectionError("transport closed")


class _BrokenReportConn:
    async def session_update(self, session_id, update) -> None:
        del session_id, update
        raise RuntimeError("report path broken")


def _content_event(text: str = "hello"):
    return SimpleNamespace(
        object="content",
        text=text,
        delta=False,
        msg_id="m1",
    )


def _unmapped_event():
    return SimpleNamespace(
        object="message",
        type="tool_result_text_delta",
        status=RunStatus.Completed,
        content=[],
    )


def _tool_start_event(call_id: str, name: str = "Bash"):
    data = {"call_id": call_id, "name": name, "arguments": "{}"}
    return SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL.value,
        status=RunStatus.Completed,
        content=[SimpleNamespace(data=data)],
    )


def _tool_output_event(call_id: str):
    data = {"call_id": call_id, "output": "done", "state": "success"}
    return SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL_OUTPUT.value,
        status=RunStatus.Completed,
        content=[SimpleNamespace(data=data)],
    )


async def _agent_with_stream(monkeypatch, stream):
    agent = QwenPawACPAgent(agent_id="default")
    conn = _RecordingConn()
    agent.on_connect(conn)

    async def _fake_workspace():
        return _FakeWorkspace(stream)

    monkeypatch.setattr(agent, "_ensure_workspace", _fake_workspace)
    session = await agent.new_session(cwd="/task")
    return agent, conn, session.session_id


def _is_keepalive(update: object) -> bool:
    meta = getattr(update, "field_meta", None) or {}
    return bool(meta.get(ACP_KEEPALIVE_META_KEY))


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("400 data_inspection_failed: inappropriate content", "refusal"),
        ("400 DataInspectionFailed", "refusal"),
        ("content policy violation", "refusal"),
        ("safety_filter triggered", "refusal"),
        ("moderation rejected the request", "refusal"),
    ],
)
def test_only_evidence_backed_moderation_markers_return_refusal(
    message: str,
    expected: str,
):
    """Content-safety markers map to refusal, including the new OSS markers."""
    assert _prompt_failure_stop_reason(RuntimeError(message)) == expected


def test_stream_idle_timeout_is_not_normalized():
    """A model stream timeout remains a failure, not a normal turn."""
    assert (
        _prompt_failure_stop_reason(
            StreamIdleTimeoutError("policy", 600.0),
        )
        is None
    )
    assert _prompt_failure_stop_reason(TimeoutError("timed out")) is None


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("boom"),
        TypeError("bad type"),
        ValueError("bad value"),
        KeyError("missing"),
        OSError("disk failure"),
        ConnectionError("database connection lost"),
        ConnectionError("connection reset by peer"),
    ],
)
def test_unconfirmed_errors_are_not_normalized(exc: Exception):
    """Unexpected exceptions must keep the JSON-RPC internal-error path."""
    assert _prompt_failure_stop_reason(exc) is None


def test_tool_output_still_maps_after_heartbeat_support():
    """Normal tool frames are unchanged by the active-call bookkeeping."""
    tracker = _EnvelopeTracker()
    start = tracker.process(_tool_start_event("call-1"))
    output = tracker.process(_tool_output_event("call-1"))

    assert len(start) == 1
    assert start[0].session_update == "tool_call"
    assert start[0].tool_call_id == "call-1"
    assert len(output) == 1
    assert output[0].session_update == "tool_call_update"
    assert output[0].status == "completed"


def test_heartbeat_emits_one_frame_per_active_tool():
    """Heartbeat frames are bounded by the number of active tool calls."""
    tracker = _EnvelopeTracker()
    tracker.process(_tool_start_event("call-a", "Bash"))
    tracker.process(_tool_start_event("call-b", "Read"))

    updates = tracker.process(
        SimpleNamespace(object="message", type="heartbeat"),
    )

    assert [update.tool_call_id for update in updates] == [
        "call-a",
        "call-b",
    ]
    assert all(update.status == "in_progress" for update in updates)

    tracker.process(_tool_output_event("call-a"))
    remaining = tracker.process(
        SimpleNamespace(object="message", type="heartbeat"),
    )
    assert [update.tool_call_id for update in remaining] == ["call-b"]


@pytest.mark.integration
async def test_short_unmapped_turn_emits_no_keepalive(monkeypatch):
    """A turn shorter than the threshold must not gain transport frames."""

    async def _stream():
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            yield _unmapped_event()

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    assert response.stop_reason == "end_turn"
    assert not [update for _, update in conn.updates if _is_keepalive(update)]


@pytest.mark.integration
async def test_normal_turn_has_no_keepalive_or_heartbeat(monkeypatch):
    """Mapped events keep the baseline frame set; no synthetic frames."""

    async def _stream():
        yield _content_event("hi")
        yield _tool_start_event("call-1")
        yield _tool_output_event("call-1")

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    assert response.stop_reason == "end_turn"
    kinds = [
        getattr(update, "session_update", "")
        for _, update in conn.updates
        if getattr(update, "session_update", "") != "available_commands_update"
    ]
    assert kinds == [
        "agent_message_chunk",
        "tool_call",
        "tool_call_update",
    ]
    assert not [update for _, update in conn.updates if _is_keepalive(update)]


@pytest.mark.integration
async def test_cancellation_still_returns_cancelled(monkeypatch):
    """The cancel path keeps its baseline stop reason and frame cutoff."""
    holder: dict[str, object] = {}

    async def _stream():
        yield _content_event("hi")
        holder["agent"]._cancel_events[holder["sid"]].set()
        yield _content_event("ignored")

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )
    holder["agent"] = agent
    holder["sid"] = session_id

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    assert response.stop_reason == "cancelled"
    texts = [
        update.content.text
        for _, update in conn.updates
        if getattr(update, "session_update", "") == "agent_message_chunk"
    ]
    assert texts == ["hi"]
    assert not [update for _, update in conn.updates if _is_keepalive(update)]


@pytest.mark.integration
async def test_keepalive_is_an_empty_marked_frame(monkeypatch):
    """Keepalive must carry no model text and no generic error marker."""

    async def _stream():
        deadline = time.monotonic() + 21.5
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            yield _unmapped_event()

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    assert response.stop_reason == "end_turn"
    frames = [update for _, update in conn.updates if _is_keepalive(update)]
    assert frames, "expected one keepalive frame after 20s"
    frame = frames[0]
    assert frame.session_update == "agent_message_chunk"
    assert frame.content.text == ""
    meta = frame.field_meta or {}
    assert meta.get(ACP_KEEPALIVE_META_KEY) is True
    assert ACP_ERROR_META_KEY not in meta


@pytest.mark.integration
async def test_disconnect_during_error_report_keeps_original_failure(
    monkeypatch,
):
    """A client disappearing during notification must not hide the failure."""

    async def _stream():
        raise ConnectionError("business connection lost")
        yield  # pragma: no cover

    agent, _conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )
    agent.on_connect(_DisconnectingConn())

    with pytest.raises(RequestError) as caught:
        await agent.prompt(
            prompt=[text_block("hello")],
            session_id=session_id,
        )

    assert caught.value.code == -32603


@pytest.mark.integration
async def test_report_failure_does_not_hide_internal_error(monkeypatch):
    """A broken notification path must not convert a bug into a normal turn."""

    async def _stream():
        raise RuntimeError("secret-token")
        yield  # pragma: no cover

    agent, _conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )
    agent.on_connect(_BrokenReportConn())

    with pytest.raises(RequestError) as caught:
        await agent.prompt(
            prompt=[text_block("hello")],
            session_id=session_id,
        )

    assert caught.value.code == -32603
    assert caught.value.data == {"details": "QwenPaw runtime failed"}


@pytest.mark.integration
async def test_internal_error_keeps_request_error_and_redacts(monkeypatch):
    """A generic runtime bug must reach the client as -32603, redacted."""

    async def _stream():
        raise RuntimeError("secret-token")
        yield  # pragma: no cover

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    with pytest.raises(RequestError) as caught:
        await agent.prompt(
            prompt=[text_block("hello")],
            session_id=session_id,
        )

    assert caught.value.code == -32603
    assert caught.value.data == {"details": "QwenPaw runtime failed"}
    rendered = str([update for _, update in conn.updates])
    assert "secret-token" not in rendered
    assert all(_is_keepalive(update) is False for _, update in conn.updates)


@pytest.mark.integration
async def test_moderation_returns_refusal_and_hides_marker(monkeypatch):
    """Moderation ends normally without leaking its details."""

    async def _stream():
        raise RuntimeError(
            "400 data_inspection_failed: inappropriate content",
        )
        yield  # pragma: no cover

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    assert response.stop_reason == "refusal"
    rendered = str([update for _, update in conn.updates])
    assert "data_inspection_failed" not in rendered
    assert "inappropriate" not in rendered
    error_frames = [
        update
        for _, update in conn.updates
        if (getattr(update, "field_meta", None) or {}).get(ACP_ERROR_META_KEY)
    ]
    assert len(error_frames) == 1
    assert "QwenPaw failed to process" in error_frames[0].content.text


async def _install_noop(self):
    return None


@pytest.mark.integration
@pytest.mark.parametrize(
    "exc",
    [ConnectionError("database lost"), RuntimeError("boom")],
)
async def test_entry_point_reraises_unrelated_errors(monkeypatch, exc):
    """Only verified transport disconnects may be swallowed at the entry."""
    calls: list[str] = []

    async def _fail(agent, use_unstable_protocol=True):
        del agent, use_unstable_protocol
        raise exc

    async def _shutdown(self):
        calls.append("shutdown")

    monkeypatch.setattr(
        acp_server.QwenPawACPAgent,
        "_install_runtime_provider",
        _install_noop,
    )
    monkeypatch.setattr(
        acp_server.QwenPawACPAgent,
        "_shutdown_workspace",
        _shutdown,
    )
    monkeypatch.setattr(acp_server, "run_agent", _fail)

    with pytest.raises(type(exc)):
        await acp_server.run_qwenpaw_agent()
    assert calls == ["shutdown"]


@pytest.mark.integration
async def test_entry_point_swallows_verified_disconnect(monkeypatch):
    """The confirmed ACP close path remains a clean shutdown."""
    calls: list[str] = []

    async def _fail(agent, use_unstable_protocol=True):
        del agent, use_unstable_protocol
        raise ConnectionError("transport closed")

    async def _shutdown(self):
        calls.append("shutdown")

    monkeypatch.setattr(
        acp_server.QwenPawACPAgent,
        "_install_runtime_provider",
        _install_noop,
    )
    monkeypatch.setattr(
        acp_server.QwenPawACPAgent,
        "_shutdown_workspace",
        _shutdown,
    )
    monkeypatch.setattr(acp_server, "run_agent", _fail)

    await acp_server.run_qwenpaw_agent()
    assert calls == ["shutdown"]

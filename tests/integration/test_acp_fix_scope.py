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
from unittest.mock import AsyncMock

import httpx
import openai
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
from qwenpaw.harnesses import runtime as harness_runtime
from qwenpaw.harnesses.events import HarnessEvent, HarnessEventKind
from qwenpaw.providers.retry_chat_model import StreamIdleTimeoutError
from qwenpaw.schemas import MessageType, RunStatus

pytestmark = pytest.mark.p1


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
    assert _prompt_failure_stop_reason(_provider_error(message)) == expected


def test_internal_error_text_is_not_content_safety():
    """Keyword-like text in internal exceptions must not become a refusal."""
    assert _prompt_failure_stop_reason(KeyError("moderation")) is None
    assert (
        _prompt_failure_stop_reason(
            NameError("name 'content_policy' is not defined"),
        )
        is None
    )


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


@pytest.mark.integration
async def test_existing_request_error_keeps_code_and_data(monkeypatch):
    """A RequestError raised by the runtime must pass through unchanged."""
    error = RequestError.invalid_params({"model_id": "x"})

    async def _stream():
        raise error
        yield  # pragma: no cover

    agent, _conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    with pytest.raises(RequestError) as caught:
        await agent.prompt(
            prompt=[text_block("hello")],
            session_id=session_id,
        )

    assert caught.value.code == -32602
    assert caught.value.data == {"model_id": "x"}


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
        raise _provider_error(
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
    [
        ConnectionError("database lost"),
        RuntimeError("boom"),
        OSError(22, f"Invalid argument"),
    ],
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


@pytest.mark.integration
@pytest.mark.parametrize(f"failure", [BrokenPipeError, RuntimeError])
async def test_final_usage_preserves_failure_boundary(monkeypatch, failure):
    """Only a transport failure may be ignored during the final flush."""
    from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

    async def stream():
        TokenRecordingModelWrapper._usage_by_session[session_id] = {
            f"total_tokens": 20,
        }
        for event in ():
            yield event

    agent, conn, session_id = await _agent_with_stream(monkeypatch, stream)

    async def fail_send(*args, **kwargs):
        raise failure(f"Final usage failed")

    monkeypatch.setattr(conn, f"session_update", fail_send)
    if failure is BrokenPipeError:
        response = await agent.prompt([text_block(f"hello")], session_id)
        assert response.stop_reason == f"end_turn"
    else:
        with pytest.raises(RuntimeError, match=f"Final usage failed"):
            await agent.prompt([text_block(f"hello")], session_id)
    assert session_id not in agent._prompt_tasks


@pytest.mark.integration
async def test_overlapping_prompt_does_not_replace_cancel_target(monkeypatch):
    """Reject overlap while retaining the original prompt's cleanup owner."""
    started = asyncio.Event()

    async def stream():
        started.set()
        await asyncio.Event().wait()
        for event in ():
            yield event

    agent, _, session_id = await _agent_with_stream(monkeypatch, stream)
    task = asyncio.create_task(
        agent.prompt([text_block(f"first")], session_id),
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(RequestError):
            await agent.prompt([text_block(f"second")], session_id)
        assert agent._prompt_tasks[session_id] is task
        await agent._cancel_active_prompt(session_id)
        assert (await task).stop_reason == f"cancelled"
        assert session_id not in agent._prompt_tasks
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.integration
async def test_config_resolution_runs_off_loop_and_reports_failure(
    monkeypatch,
):
    """Slow config reads keep the transport alive and preserve real errors."""
    import threading

    loop_thread = threading.get_ident()

    async def stream():
        for event in ():
            yield event

    agent, conn, session_id = await _agent_with_stream(monkeypatch, stream)
    monkeypatch.setattr(acp_server, f"_ACP_KEEPALIVE_SECONDS", 0.01)

    def resolve():
        assert threading.get_ident() != loop_thread
        time.sleep(0.08)
        raise OSError(f"Configuration unreadable")

    monkeypatch.setattr(agent, f"_resolve_agent_id", resolve)
    with pytest.raises(RequestError):
        await agent.prompt([text_block(f"hello")], session_id)
    assert any(_is_keepalive(update) for _, update in conn.updates)
    assert session_id not in agent._prompt_tasks
    assert session_id not in agent._cancel_events


@pytest.mark.integration
async def test_disconnect_does_not_write_an_error_frame(monkeypatch):
    """Stop writing as soon as the transport reports a disconnect."""

    async def stream():
        yield _content_event(f"tail")

    monkeypatch.setattr(
        QwenPawACPAgent,
        f"_advertise_commands",
        AsyncMock(),
    )
    agent, conn, session_id = await _agent_with_stream(monkeypatch, stream)
    send = AsyncMock(side_effect=BrokenPipeError())
    monkeypatch.setattr(conn, f"session_update", send)
    response = await agent.prompt([text_block(f"hello")], session_id)
    assert response.stop_reason == f"end_turn"
    assert send.await_count == 1
    assert session_id not in agent._prompt_tasks


@pytest.mark.integration
@pytest.mark.parametrize(
    f"outcome",
    [f"error", f"cancelled", f"completed", f"exception"],
)
async def test_harness_terminal_preserves_output_and_status(
    monkeypatch,
    tmp_path,
    outcome,
):
    """Exercise real harness envelopes, including errors caught by it."""
    runtime = harness_runtime.HarnessRuntime(tmp_path)
    monkeypatch.setattr(
        runtime._capability_resolver,
        f"resolve",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        harness_runtime,
        f"record_agent_activity",
        AsyncMock(),
    )

    async def run_turn(**kwargs):
        del kwargs
        yield HarnessEvent(kind=HarnessEventKind.TEXT_DELTA, text=f"tail")
        if outcome == f"exception":
            raise RuntimeError(f"backend secret")
        yield HarnessEvent(
            kind=HarnessEventKind(outcome),
            text=f"backend secret",
        )

    monkeypatch.setattr(
        runtime,
        f"adapter",
        AsyncMock(return_value=SimpleNamespace(run_turn=run_turn)),
    )
    agent = QwenPawACPAgent(agent_id=f"default")
    conn = _RecordingConn()
    agent.on_connect(conn)
    session_id = f"harness-review"
    agent._sessions[session_id] = {f"user_id": session_id}

    async def stream_query(request):
        async for event in runtime.stream(
            backend=f"codex",
            request=request,
            cwd=tmp_path,
        ):
            yield event

    monkeypatch.setattr(
        agent,
        f"_ensure_workspace",
        AsyncMock(return_value=SimpleNamespace(stream_query=stream_query)),
    )
    if outcome in {f"error", f"exception"}:
        with pytest.raises(RequestError) as caught:
            await agent.prompt([text_block(f"hello")], session_id)
        assert caught.value.code == -32603
    else:
        response = await agent.prompt([text_block(f"hello")], session_id)
        expected = f"cancelled" if outcome == f"cancelled" else f"end_turn"
        assert response.stop_reason == expected
    texts = [
        update.content.text
        for _, update in conn.updates
        if getattr(update, f"session_update", None) == f"agent_message_chunk"
    ]
    assert texts[0] == f"tail"
    assert f"backend secret" not in str(texts)
    assert session_id not in agent._prompt_tasks


@pytest.mark.integration
@pytest.mark.parametrize(
    f"failure",
    [
        _provider_error(f"inappropriate content"),
        StreamIdleTimeoutError(f"model", 120.0),
        RequestError.invalid_params({f"details": f"original"}),
    ],
)
async def test_native_exception_overrides_failure_envelope(
    monkeypatch,
    failure,
):
    """Keep original exception semantics after draining queued output."""

    async def stream():
        yield _content_event(f"tail")
        yield SimpleNamespace(
            object=f"response",
            status=RunStatus.Failed,
            error={f"message": f"inappropriate content"},
        )
        raise failure

    agent, conn, session_id = await _agent_with_stream(monkeypatch, stream)
    if isinstance(failure, openai.APIError):
        response = await agent.prompt([text_block(f"hello")], session_id)
        assert response.stop_reason == f"refusal"
    else:
        with pytest.raises(RequestError) as caught:
            await agent.prompt([text_block(f"hello")], session_id)
        if isinstance(failure, RequestError):
            assert caught.value is failure
        else:
            assert caught.value.code == -32603
    texts = [
        update.content.text
        for _, update in conn.updates
        if getattr(update, f"session_update", None) == f"agent_message_chunk"
    ]
    assert texts[0] == f"tail"

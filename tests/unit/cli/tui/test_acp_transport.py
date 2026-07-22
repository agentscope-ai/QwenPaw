# -*- coding: utf-8 -*-
"""End-to-end test of AcpTransport against a fake ACP agent subprocess."""

from __future__ import annotations

# Tests assert on transport internals for focused coverage.
# pylint: disable=protected-access

import asyncio
import os
import sys
import time
from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.meta import (
    ACP_APPROVAL_EXPIRES_AT_META_KEY,
    ACP_CODING_PROJECT_META_KEY,
)
from qwenpaw.cli.tui.events import (
    BackendWarmed,
    Connected,
    PermissionExpired,
    PermissionRequest,
    TextDelta,
    ThoughtDelta,
    ToolCall,
    TransportError,
    TurnEnded,
    UserTurn,
)
from qwenpaw.cli.tui.transport.acp import AcpTransport, _TuiClient

pytestmark = [pytest.mark.unit, pytest.mark.p1]

FAKE = os.path.join(os.path.dirname(__file__), "_fake_acp_agent.py")


def _transport() -> AcpTransport:
    return AcpTransport(command=[sys.executable, FAKE])


def test_session_kwargs_include_project_dir():
    transport = AcpTransport(
        command=[sys.executable, FAKE],
        project_dir="/tmp/project",
    )
    assert transport._session_kwargs() == {
        ACP_CODING_PROJECT_META_KEY: "/tmp/project",
    }


async def _collect_turn(transport: AcpTransport, *, timeout: float = 10.0):
    """Drain events until TurnEnded; return the list."""
    events = []

    async def _run():
        async for ev in transport.events():
            events.append(ev)
            if isinstance(ev, TurnEnded):
                return

    await asyncio.wait_for(_run(), timeout=timeout)
    return events


@pytest.mark.asyncio
async def test_start_and_basic_turn():
    transport = _transport()
    try:
        connected = await asyncio.wait_for(transport.start(), timeout=10.0)
        assert isinstance(connected, Connected)
        assert connected.session_id == "sess-1"
        assert connected.qwenpaw_version == "0.0.1"
        assert connected.warming is True

        await transport.send("hi there")
        events = await _collect_turn(transport)
    finally:
        await transport.close()

    assert any(isinstance(e, ThoughtDelta) for e in events)
    assert any(isinstance(e, BackendWarmed) for e in events)
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text == "Hello world"

    # ACP sends a start (carries the title) then an update (carries status/
    # output) sharing one tool_call_id; the UI merges them by id.
    tools = [e for e in events if isinstance(e, ToolCall)]
    assert any(
        t.title == "read_file"
        and t.kind == "read"
        and t.params == "path: README.md"
        for t in tools
    )
    assert any(
        t.tool_call_id == "t2"
        and t.status == "completed"
        and t.output == "file contents"
        for t in tools
    )
    assert not any(isinstance(e, TransportError) for e in events)
    assert isinstance(events[-1], TurnEnded)


@pytest.mark.asyncio
async def test_permission_allow():
    transport = _transport()
    try:
        await asyncio.wait_for(transport.start(), timeout=10.0)
        await transport.send("please need-permission now")

        # Drive the turn, answering the permission prompt with "allow".
        events = []

        async def _run():
            async for ev in transport.events():
                events.append(ev)
                if isinstance(ev, PermissionRequest):
                    assert {o.option_id for o in ev.options} == {
                        "allow",
                        "deny",
                    }
                    assert ev.params == "command: rm -rf /tmp/nope"
                    await transport.resolve_permission(ev.request_id, "allow")
                if isinstance(ev, TurnEnded):
                    return

        await asyncio.wait_for(_run(), timeout=10.0)
    finally:
        await transport.close()

    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert "[perm:allow]" in text


@pytest.mark.asyncio
async def test_permission_cancellation_emits_expired_event():
    queue = asyncio.Queue()
    client = _TuiClient(queue)
    task = asyncio.create_task(
        client.request_permission(
            options=[],
            session_id="sess-1",
            tool_call=SimpleNamespace(
                title="dangerous_tool",
                kind="execute",
                raw_input={"command": "rm -rf /tmp/nope"},
            ),
        ),
    )

    request = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert isinstance(request, PermissionRequest)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    expired = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert isinstance(expired, PermissionExpired)
    assert expired.request_id == request.request_id
    assert "no longer pending" in expired.message


@pytest.mark.asyncio
async def test_permission_timeout_cancellation_emits_timeout_message():
    queue = asyncio.Queue()
    client = _TuiClient(queue)
    task = asyncio.create_task(
        client.request_permission(
            options=[],
            session_id="sess-1",
            tool_call=SimpleNamespace(
                title="dangerous_tool",
                kind="execute",
                raw_input={"command": "rm -rf /tmp/nope"},
            ),
        ),
    )

    request = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert isinstance(request, PermissionRequest)

    task.cancel("timeout")
    with pytest.raises(asyncio.CancelledError):
        await task

    expired = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert isinstance(expired, PermissionExpired)
    assert expired.request_id == request.request_id
    assert "timed out" in expired.message
    assert "blocked" in expired.message


@pytest.mark.asyncio
async def test_permission_request_carries_expiry_metadata():
    queue = asyncio.Queue()
    client = _TuiClient(queue)
    expires_at = time.time() + 300.0
    task = asyncio.create_task(
        client.request_permission(
            options=[],
            session_id="sess-1",
            tool_call=SimpleNamespace(
                title="dangerous_tool",
                kind="execute",
                raw_input={"command": "rm -rf /tmp/nope"},
                field_meta={
                    ACP_APPROVAL_EXPIRES_AT_META_KEY: expires_at,
                },
            ),
        ),
    )

    request = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert isinstance(request, PermissionRequest)
    assert request.expires_at == expires_at

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_permission_expires_locally_at_deadline(monkeypatch):
    """ACP has no agent→client cancel, so the client enforces the deadline
    itself: past the advertised expiry the handler answers "cancelled" and
    emits PermissionExpired so the overlay clears with an explanation.
    """
    monkeypatch.setattr(
        "qwenpaw.cli.tui.transport.acp._PERMISSION_EXPIRY_GRACE_SECONDS",
        10.0,
    )
    queue = asyncio.Queue()
    client = _TuiClient(queue)
    task = asyncio.create_task(
        client.request_permission(
            options=[],
            session_id="sess-1",
            tool_call=SimpleNamespace(
                title="dangerous_tool",
                kind="execute",
                raw_input={"command": "rm -rf /tmp/nope"},
                field_meta={
                    ACP_APPROVAL_EXPIRES_AT_META_KEY: time.time() - 20.0,
                },
            ),
        ),
    )

    request = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert isinstance(request, PermissionRequest)

    response = await asyncio.wait_for(task, timeout=0.5)
    assert response.outcome.outcome == "cancelled"

    expired = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert isinstance(expired, PermissionExpired)
    assert expired.request_id == request.request_id
    assert "timed out" in expired.message

    # A late resolve after expiry must be a harmless no-op.
    client.resolve(request.request_id, "allow_once")


@pytest.mark.asyncio
async def test_interrupt_cancels_turn():
    transport = _transport()
    try:
        await asyncio.wait_for(transport.start(), timeout=10.0)
        await transport.send("please loop forever")

        events = []
        seen_tool = asyncio.Event()

        async def _run():
            async for ev in transport.events():
                events.append(ev)
                if isinstance(ev, ToolCall) and ev.status == "completed":
                    seen_tool.set()
                if isinstance(ev, TurnEnded):
                    return

        runner = asyncio.create_task(_run())
        await asyncio.wait_for(seen_tool.wait(), timeout=10.0)
        await transport.interrupt()
        await asyncio.wait_for(runner, timeout=10.0)
    finally:
        await transport.close()

    assert isinstance(events[-1], TurnEnded)


@pytest.mark.asyncio
async def test_list_sessions():
    transport = _transport()
    try:
        await asyncio.wait_for(transport.start(), timeout=10.0)
        sessions = await asyncio.wait_for(
            transport.list_sessions(),
            timeout=10.0,
        )
    finally:
        await transport.close()

    assert len(sessions) == 1
    assert sessions[0].session_id == "old-session-1"
    assert sessions[0].title == "Earlier chat about Rust"
    assert sessions[0].updated_at


@pytest.mark.asyncio
async def test_start_with_resume_loads_and_replays():
    transport = AcpTransport(
        command=[sys.executable, FAKE],
        resume_session_id="old-session-1",
    )
    try:
        connected = await asyncio.wait_for(transport.start(), timeout=10.0)
        # start() loaded the requested session instead of opening a new one.
        assert connected.session_id == "old-session-1"
        assert transport.session_id == "old-session-1"

        events = []

        async def _run():
            async for ev in transport.events():
                events.append(ev)
                if len([e for e in events if isinstance(e, UserTurn)]) >= 2:
                    return

        await asyncio.wait_for(_run(), timeout=5.0)
    finally:
        await transport.close()

    users = [e.text for e in events if isinstance(e, UserTurn)]
    assert users == ["How do I write a loop in Rust?", "Thanks!"]


@pytest.mark.asyncio
async def test_load_session_replays_history():
    transport = _transport()
    try:
        await asyncio.wait_for(transport.start(), timeout=10.0)
        await asyncio.wait_for(
            transport.load_session("old-session-1"),
            timeout=10.0,
        )
        assert transport.session_id == "old-session-1"
        # The replayed history is delivered as session updates; drain until
        # both replayed user turns have arrived (a BackendWarmed event from
        # the warmup may be interleaved ahead of them).
        events = []

        async def _run():
            async for ev in transport.events():
                events.append(ev)
                if len([e for e in events if isinstance(e, UserTurn)]) >= 2:
                    return

        await asyncio.wait_for(_run(), timeout=5.0)
    finally:
        await transport.close()

    user_turns = [e for e in events if isinstance(e, UserTurn)]
    assert [u.text for u in user_turns] == [
        "How do I write a loop in Rust?",
        "Thanks!",
    ]
    replayed = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert "Use a `for` loop over a range." in replayed


def test_session_agent_reads_meta():
    from qwenpaw.cli.tui.transport.acp import _session_agent

    # Agent id reported via the session response _meta.
    sess = SimpleNamespace(field_meta={"qwenpaw.agent": "writer"})
    assert _session_agent(sess) == "writer"

    # Missing / unrelated meta → None (caller falls back to the requested id).
    assert _session_agent(SimpleNamespace(field_meta={"other": 1})) is None
    assert _session_agent(SimpleNamespace(field_meta=None)) is None

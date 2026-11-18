# -*- coding: utf-8 -*-
"""ACP streaming regressions and real stdio shutdown checks."""

# pylint: disable=protected-access,unreachable,unused-argument

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import os
import pathlib
import sys
import time
from types import SimpleNamespace

import pytest
from acp import (
    PROTOCOL_VERSION,
    RequestError,
    connect_to_agent,
    text_block,
)
from acp.stdio import spawn_agent_process

import qwenpaw
from qwenpaw.agents.acp import server as acp_server
from qwenpaw.agents.acp.server import (
    ACP_KEEPALIVE_META_KEY,
    QwenPawACPAgent,
)
from qwenpaw.schemas import MessageType, RunStatus

pytestmark = pytest.mark.p1


DRIVER = pathlib.Path(__file__).with_name("_acp_fault_driver.py")
SRC_DIR = pathlib.Path(qwenpaw.__file__).resolve().parents[1]


class _RecordingConn:
    """Record ACP notifications for output assertions."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, object]] = []

    async def session_update(self, session_id, update) -> None:
        self.updates.append((session_id, update))


class _FakeWorkspace:
    def __init__(self, stream) -> None:
        self._stream = stream

    async def stream_query(self, request):
        del request
        async for event in self._stream():
            yield event


def _content_event(text: str = "ok"):
    return SimpleNamespace(
        object="content",
        text=text,
        delta=False,
        msg_id="m1",
    )


def _unmapped_event():
    return SimpleNamespace(
        object="message",
        type=f"tool_result_text_delta",
        status=RunStatus.Completed,
        content=[],
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


@pytest.mark.integration
async def test_keepalive_covers_wait_before_first_event(monkeypatch):
    """Pre-hooks and agent build must not leave the client without frames."""

    monkeypatch.setattr(acp_server, "_ACP_KEEPALIVE_SECONDS", 0.1)

    async def _stream():
        await asyncio.sleep(0.45)
        yield SimpleNamespace(
            object="content",
            text="ok",
            delta=False,
            msg_id="m1",
        )

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    keepalives = [
        update
        for _, update in conn.updates
        if (getattr(update, "field_meta", None) or {}).get(
            ACP_KEEPALIVE_META_KEY,
        )
    ]
    assert response.stop_reason == "end_turn"
    assert len(keepalives) >= 2
    assert all(update.content.text == f"" for update in keepalives)
    assert any(
        getattr(getattr(update, f"content", None), f"text", None) == f"ok"
        for _, update in conn.updates
    )


@pytest.mark.integration
async def test_keepalive_covers_workspace_initialization(monkeypatch):
    """Workspace creation and its lock wait must also emit keepalives."""

    monkeypatch.setattr(acp_server, "_ACP_KEEPALIVE_SECONDS", 0.1)

    async def _normal_stream():
        yield _content_event("ok")

    agent = QwenPawACPAgent(agent_id="default")
    conn = _RecordingConn()
    agent.on_connect(conn)

    async def _slow_workspace():
        await asyncio.sleep(0.45)
        return _FakeWorkspace(_normal_stream)

    monkeypatch.setattr(agent, "_ensure_workspace", _slow_workspace)
    session = await agent.new_session(cwd="/task")

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session.session_id,
    )

    keepalives = [
        update
        for _, update in conn.updates
        if (getattr(update, "field_meta", None) or {}).get(
            ACP_KEEPALIVE_META_KEY,
        )
    ]
    assert response.stop_reason == "end_turn"
    assert len(keepalives) >= 2


@pytest.mark.integration
async def test_ready_unmapped_events_do_not_starve_keepalive(monkeypatch):
    """Keepalive is based on emit time, not only on an empty wait timeout."""

    monkeypatch.setattr(acp_server, "_ACP_KEEPALIVE_SECONDS", 0.05)

    async def _stream():
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            yield _unmapped_event()

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    keepalives = [
        update
        for _, update in conn.updates
        if (getattr(update, "field_meta", None) or {}).get(
            ACP_KEEPALIVE_META_KEY,
        )
    ]
    assert response.stop_reason == "end_turn"
    assert keepalives


@pytest.mark.integration
async def test_contextvars_persist_across_stream_events(monkeypatch):
    """The whole turn must run in one task so ContextVars survive yields."""

    marker = contextvars.ContextVar("marker", default=None)
    seen: list[str | None] = []

    async def _stream():
        marker.set("set-by-runtime-hook")
        yield _content_event("one")
        seen.append(marker.get())
        yield _content_event("two")

    agent, _conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    assert response.stop_reason == "end_turn"
    assert seen == ["set-by-runtime-hook"]


@pytest.mark.integration
async def test_mutable_events_are_snapshotted_before_queue(monkeypatch):
    """One mutable runtime event must not produce duplicate ACP updates."""
    data = {"call_id": "call-1", "name": "Bash", "arguments": "{}"}
    event = SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL.value,
        status=RunStatus.InProgress,
        content=[SimpleNamespace(data=data)],
    )

    async def _stream():
        yield event
        event.status = RunStatus.Completed
        yield event

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    starts = [
        update
        for _, update in conn.updates
        if getattr(update, "session_update", "") == "tool_call"
    ]
    assert response.stop_reason == "end_turn"
    assert len(starts) == 1


@pytest.mark.integration
@pytest.mark.parametrize(f"cancel_task", [False, True])
async def test_runtime_cancellation_returns_cancelled(
    monkeypatch,
    cancel_task,
):
    """A runtime-issued Task.cancel must also preserve cancellation state."""

    async def _stream():
        if not cancel_task:
            raise asyncio.CancelledError(f"runtime cancelled")
        task = asyncio.current_task()
        assert task is not None
        task.cancel("timeout")
        while True:
            await asyncio.sleep(0)
            yield _content_event("ignored")

    agent, _conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    assert response.stop_reason == "cancelled"


@pytest.mark.integration
async def test_queue_full_cancel_does_not_deadlock(monkeypatch):
    """Cancelling while the pump waits on a full queue must clean up."""

    monkeypatch.setattr(acp_server, "_ACP_KEEPALIVE_SECONDS", 10.0)
    blocker = asyncio.Event()

    async def _stream():
        for index in range(20):
            yield _content_event(f"x{index}")

    agent, _conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )
    original_send = agent._send_update

    async def _blocked_send(session_id, update):
        await blocker.wait()
        await original_send(session_id, update)

    monkeypatch.setattr(agent, "_send_update", _blocked_send)

    prompt_task = asyncio.create_task(
        agent.prompt(
            prompt=[text_block("hello")],
            session_id=session_id,
        ),
    )
    await asyncio.sleep(0.1)
    prompt_task.cancel()

    response = await asyncio.wait_for(prompt_task, timeout=2)
    assert response.stop_reason == "cancelled"
    assert session_id not in agent._prompt_tasks
    assert session_id not in agent._cancel_events


@pytest.mark.integration
async def test_backpressure_preserves_all_output_before_end(monkeypatch):
    """The pump must not run unboundedly ahead of the ACP consumer."""
    monkeypatch.setattr(acp_server, "_ACP_KEEPALIVE_SECONDS", 10.0)
    produced = 0
    consumed = 0
    max_lag = 0

    async def _stream():
        nonlocal produced, max_lag
        for index in range(20):
            produced += 1
            max_lag = max(max_lag, produced - consumed)
            yield _content_event(f"x{index}")

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )
    original_send = agent._send_update

    async def _slow_send(session_id, update):
        nonlocal consumed
        await asyncio.sleep(0.01)
        await original_send(session_id, update)
        consumed += 1

    monkeypatch.setattr(agent, "_send_update", _slow_send)

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    assert response.stop_reason == "end_turn"
    assert max_lag <= 3, f"producer ran {max_lag} events ahead"

    texts = [
        update.content.text
        for _, update in conn.updates
        if getattr(update, f"session_update", None) == f"agent_message_chunk"
        and update.content.text
    ]
    assert texts == [f"x{index}" for index in range(20)]


def _driver_env(scenario: str, tmp_dir: pathlib.Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(SRC_DIR),
            env.get("PYTHONPATH", ""),
        )
        if part
    )
    env["QWENPAW_FAULT_SCENARIO"] = scenario
    env["QWENPAW_WORKING_DIR"] = str(tmp_dir / "qwenpaw-state")
    env["QWENPAW_SECRET_DIR"] = str(tmp_dir / "qwenpaw-secrets")
    return env


class _SubprocessClient:
    def __init__(self) -> None:
        self.updates: list[object] = []
        self.first_update = asyncio.Event()

    async def session_update(self, session_id, update, **kwargs) -> None:
        self.updates.append(update)
        self.first_update.set()

    async def request_permission(
        self,
        options,
        session_id,
        tool_call,
        **kwargs,
    ):
        raise AssertionError("fake workspace never requests permission")


@pytest.mark.integration
@pytest.mark.parametrize(f"close_stdout", [False, True])
async def test_subprocess_active_pipe_close_exits_cleanly(
    tmp_path,
    close_stdout,
):
    """Closing stdin or both pipes must clean up and exit without errors."""

    marker = tmp_path / "shutdown.marker"
    env = _driver_env("hang", tmp_path)
    env["QWENPAW_FAULT_MARKER"] = str(marker)
    client = _SubprocessClient()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(DRIVER),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(pathlib.Path(__file__).resolve().parents[2]),
    )
    conn = connect_to_agent(client, process.stdin, process.stdout)
    try:
        await conn.initialize(protocol_version=PROTOCOL_VERSION)
        session = await conn.new_session(cwd=str(tmp_path))
        prompt_task = asyncio.create_task(
            conn.prompt(
                prompt=[text_block("hello")],
                session_id=session.session_id,
            ),
        )
        await asyncio.wait_for(client.first_update.wait(), timeout=5)

        process.stdin.close()
        with contextlib.suppress(Exception):
            await process.stdin.wait_closed()
        if close_stdout:
            process.stdout._transport.close()  # type: ignore[attr-defined]

        with contextlib.suppress(Exception):
            await asyncio.wait_for(prompt_task, timeout=2)
        await asyncio.wait_for(process.wait(), timeout=10)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()

    stderr = b""
    if process.stderr is not None:
        with contextlib.suppress(Exception):
            stderr = await process.stderr.read()
    assert process.returncode == 0, stderr.decode(errors="replace")
    assert marker.read_text(encoding="utf-8") == "shutdown"


@pytest.mark.integration
@pytest.mark.parametrize(f"scenario", [f"moderation", f"idle"])
async def test_subprocess_preserves_failure_contract(tmp_path, scenario):
    """JSON-RPC errors and refusals differ even when both processes exit 0."""
    client = _SubprocessClient()
    async with spawn_agent_process(
        client,
        sys.executable,
        str(DRIVER),
        env=_driver_env(scenario, tmp_path),
        cwd=str(pathlib.Path(__file__).resolve().parents[2]),
    ) as (conn, process):
        await conn.initialize(protocol_version=PROTOCOL_VERSION)
        session = await conn.new_session(cwd=str(tmp_path))
        prompt = conn.prompt(
            prompt=[text_block(f"hello")],
            session_id=session.session_id,
        )
        if scenario == f"moderation":
            assert (await prompt).stop_reason == f"refusal"
        else:
            with pytest.raises(RequestError) as caught:
                await prompt
            assert caught.value.code == -32603
            assert caught.value.data == {f"details": f"QwenPaw runtime failed"}
    assert process.returncode == 0
    assert f"data_inspection_failed" not in str(client.updates)

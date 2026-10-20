# -*- coding: utf-8 -*-
"""Fault-injection tests for ACP liveness and task-level exit semantics.

The tests drive the real ``QwenPawACPAgent.prompt`` loop with a fake
workspace.  They reproduce the two failure classes seen in the
benchmark:

* events that never map to an ACP frame starve the transport, and
* expected task failures escape ``prompt`` as ``RequestError`` so the
  agent process can end nonzero.

All timings use the production keepalive threshold.  The subprocess
tests additionally assert the real process exit code, which is what the
benchmark harness classifies as ``NonZeroAgentExitCodeError``.
"""

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

import httpx
import openai
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
from qwenpaw.agents.acp.server import QwenPawACPAgent
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


# The baseline revision does not define these constants; keeping the
# lookups lazy lets the same file run as the A/B control.
KEEPALIVE_META_KEY = getattr(
    acp_server,
    "ACP_KEEPALIVE_META_KEY",
    "qwenpaw.keepalive",
)
HEARTBEAT_TYPE = "heartbeat"
UNMAPPED_EVENT_TYPE = "tool_result_text_delta"

DRIVER = pathlib.Path(__file__).with_name("_acp_fault_driver.py")
SRC_DIR = pathlib.Path(qwenpaw.__file__).resolve().parents[1]


class _RecordingConn:
    """Record every ACP notification with a monotonic timestamp."""

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


def _tool_start_event(call_id: str = "call-1"):
    data = {"call_id": call_id, "name": "Bash", "arguments": "{}"}
    return SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL.value,
        status=RunStatus.Completed,
        content=[SimpleNamespace(data=data)],
    )


def _tool_output_event(call_id: str = "call-1"):
    data = {"call_id": call_id, "output": "done", "state": "success"}
    return SimpleNamespace(
        object="message",
        type=MessageType.PLUGIN_CALL_OUTPUT.value,
        status=RunStatus.Completed,
        content=[SimpleNamespace(data=data)],
    )


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
        type=UNMAPPED_EVENT_TYPE,
        status=RunStatus.Completed,
        content=[],
    )


def _heartbeat_event():
    return SimpleNamespace(object="message", type=HEARTBEAT_TYPE)


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
async def test_unmapped_deltas_emit_keepalive_at_production_threshold(
    monkeypatch,
):
    """A stream of unmapped deltas must still produce ACP frames."""

    threshold = getattr(acp_server, "_ACP_KEEPALIVE_SECONDS", 20.0)
    run_for = threshold + 3.0

    async def _stream():
        deadline = time.monotonic() + run_for
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            yield _unmapped_event()

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    started = time.monotonic()
    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )
    elapsed = time.monotonic() - started

    keepalives = [
        ts
        for (_, update), ts in zip(conn.updates, conn.times)
        if (getattr(update, "field_meta", None) or {}).get(
            KEEPALIVE_META_KEY,
        )
    ]

    assert response.stop_reason == "end_turn"
    assert keepalives, (
        f"no keepalive frame in {elapsed:.1f}s; "
        f"updates={len(conn.updates)}"
    )
    first_delay = keepalives[0] - started
    assert threshold - 1.0 <= first_delay <= threshold + 3.0, (
        f"first keepalive after {first_delay:.1f}s; "
        f"expected about {threshold:.1f}s"
    )


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
            KEEPALIVE_META_KEY,
        )
    ]
    assert response.stop_reason == "end_turn"
    assert len(keepalives) >= 2


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
            KEEPALIVE_META_KEY,
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
            await asyncio.sleep(0.001)
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
            KEEPALIVE_META_KEY,
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
async def test_runtime_cancelled_error_returns_cancelled(monkeypatch):
    """A CancelledError from the runtime itself is not a normal end."""

    async def _stream():
        raise asyncio.CancelledError("timeout")
        yield  # pragma: no cover

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
async def test_task_cancel_returns_cancelled(monkeypatch):
    """A runtime-issued Task.cancel must also preserve cancellation state."""

    async def _stream():
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
async def test_queue_applies_backpressure_to_producer(monkeypatch):
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

    agent, _conn, session_id = await _agent_with_stream(
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


@pytest.mark.integration
async def test_terminal_waits_for_queued_updates(monkeypatch):
    """A terminal signal must not overtake updates already queued."""

    monkeypatch.setattr(acp_server, "_ACP_KEEPALIVE_SECONDS", 10.0)

    async def _stream():
        for index in range(5):
            yield _content_event(f"x{index}")

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )
    original_send = agent._send_update

    async def _slow_send(session_id, update):
        await asyncio.sleep(0.02)
        await original_send(session_id, update)

    monkeypatch.setattr(agent, "_send_update", _slow_send)

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    texts = [
        update.content.text
        for _, update in conn.updates
        if getattr(update, "session_update", "") == "agent_message_chunk"
        and getattr(getattr(update, "content", None), "text", "")
    ]
    assert response.stop_reason == "end_turn"
    assert texts == [f"x{index}" for index in range(5)]


@pytest.mark.integration
async def test_keepalive_does_not_cancel_pending_event(monkeypatch):
    """Keepalive timeouts must reuse the pending ``__anext__`` future."""

    monkeypatch.setattr(acp_server, "_ACP_KEEPALIVE_SECONDS", 0.1)
    cancelled = False

    async def _stream():
        nonlocal cancelled
        try:
            await asyncio.sleep(0.45)
            yield SimpleNamespace(
                object="content",
                text="ok",
                delta=False,
                msg_id="m1",
            )
        except asyncio.CancelledError:
            cancelled = True
            raise

    agent, _conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )

    assert response.stop_reason == "end_turn"
    assert cancelled is False


@pytest.mark.integration
async def test_silent_tool_heartbeats_keep_transport_alive(monkeypatch):
    """Runtime heartbeats for an active tool must become ACP frames.

    A silent tool emits no events except the runtime heartbeat.  The
    baseline tracker drops those heartbeats, leaving a gap as long as
    the tool call itself.
    """

    heartbeat_interval = 25.0
    beats = 2

    async def _stream():
        yield _tool_start_event()
        for _ in range(beats):
            await asyncio.sleep(heartbeat_interval)
            yield _heartbeat_event()
        yield _tool_output_event()

    agent, conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    response = await agent.prompt(
        prompt=[text_block("hello")],
        session_id=session_id,
    )
    finished = time.monotonic()

    assert response.stop_reason == "end_turn"
    assert len(conn.updates) >= 1 + beats, (
        "expected tool start plus one frame per heartbeat; "
        f"got {len(conn.updates)}"
    )
    heartbeat_updates = [
        update
        for _, update in conn.updates
        if getattr(update, "session_update", "") == "tool_call_update"
        and getattr(update, "status", "") == "in_progress"
    ]
    assert len(heartbeat_updates) >= beats

    max_gap = max(
        later - earlier for earlier, later in zip(conn.times, conn.times[1:])
    )
    tail_gap = finished - conn.times[-1]
    assert max_gap <= 30.0, f"frame gap {max_gap:.1f}s exceeds 30s"
    assert tail_gap <= 30.0, f"tail gap {tail_gap:.1f}s exceeds 30s"


@pytest.mark.integration
async def test_content_moderation_returns_refusal(monkeypatch):
    """Aliyun moderation errors must end as an ACP refusal, not an error."""

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
    assert "data_inspection_failed" not in str(conn.updates)


@pytest.mark.integration
async def test_stream_idle_timeout_keeps_request_error(monkeypatch):
    """An idle model stream must keep its failure signal."""

    async def _stream():
        raise StreamIdleTimeoutError("policy", 600.0)
        yield  # pragma: no cover

    agent, _conn, session_id = await _agent_with_stream(
        monkeypatch,
        _stream,
    )

    with pytest.raises(RequestError) as exc_info:
        await agent.prompt(
            prompt=[text_block("hello")],
            session_id=session_id,
        )

    assert exc_info.value.code == -32603
    assert exc_info.value.data == {
        "details": "QwenPaw runtime failed",
    }


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


async def _prompt_via_subprocess(scenario: str, tmp_path):
    observed: dict[str, object] = {
        "scenario": scenario,
        "stop_reason": None,
        "prompt_error": None,
        "error_code": None,
        "error_data": None,
        "client_updates": [],
        "exit_code": None,
    }
    env = _driver_env(scenario, tmp_path)
    client = _SubprocessClient()

    async with spawn_agent_process(
        client,
        sys.executable,
        str(DRIVER),
        env=env,
        cwd=str(pathlib.Path(__file__).resolve().parents[2]),
    ) as (conn, process):
        try:
            await conn.initialize(protocol_version=PROTOCOL_VERSION)
            session = await conn.new_session(cwd=str(tmp_path))
            response = await conn.prompt(
                prompt=[text_block("hello")],
                session_id=session.session_id,
            )
            observed["stop_reason"] = response.stop_reason
        except RequestError as exc:
            observed["prompt_error"] = f"{type(exc).__name__}: {exc}"
            observed["error_code"] = exc.code
            observed["error_data"] = exc.data
        except Exception as exc:  # noqa: BLE001 - recorded for the A/B run
            observed["prompt_error"] = f"{type(exc).__name__}: {exc}"

    observed["client_updates"] = [str(update) for update in client.updates]
    # The transport closes stdin and waits for a graceful exit; the
    # return code is only final after the context manager unwinds.
    observed["exit_code"] = process.returncode
    return observed


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
async def test_run_agent_swallows_client_disconnect(monkeypatch):
    """A dropped transport must not escape the agent entry point."""

    calls: list[str] = []

    async def _install(self):
        calls.append("install")

    async def _shutdown(self):
        calls.append("shutdown")

    async def _disconnect(agent, use_unstable_protocol=True):
        del agent, use_unstable_protocol
        raise ConnectionError("transport closed")

    monkeypatch.setattr(
        acp_server.QwenPawACPAgent,
        "_install_runtime_provider",
        _install,
    )
    monkeypatch.setattr(
        acp_server.QwenPawACPAgent,
        "_shutdown_workspace",
        _shutdown,
    )
    monkeypatch.setattr(acp_server, "run_agent", _disconnect)

    await acp_server.run_qwenpaw_agent()

    assert calls == ["install", "shutdown"]


@pytest.mark.integration
async def test_run_agent_does_not_swallow_internal_errors(monkeypatch):
    """Only the ACP transport boundary may absorb connection failures."""

    async def _install(self):
        return None

    async def _shutdown(self):
        return None

    async def _boom(agent, use_unstable_protocol=True):
        del agent, use_unstable_protocol
        raise RuntimeError("internal bug")

    monkeypatch.setattr(
        acp_server.QwenPawACPAgent,
        "_install_runtime_provider",
        _install,
    )
    monkeypatch.setattr(
        acp_server.QwenPawACPAgent,
        "_shutdown_workspace",
        _shutdown,
    )
    monkeypatch.setattr(acp_server, "run_agent", _boom)

    with pytest.raises(RuntimeError, match="internal bug"):
        await acp_server.run_qwenpaw_agent()


@pytest.mark.integration
async def test_subprocess_moderation_prompt_returns_refusal_and_exit_zero(
    tmp_path,
):
    observed = await _prompt_via_subprocess("moderation", tmp_path)

    assert observed["prompt_error"] is None, observed
    assert observed["stop_reason"] == "refusal", observed
    assert observed["exit_code"] == 0, observed


@pytest.mark.integration
async def test_subprocess_idle_prompt_keeps_request_error(tmp_path):
    observed = await _prompt_via_subprocess("idle", tmp_path)

    assert observed["stop_reason"] is None, observed
    assert observed["error_code"] == -32603, observed
    assert observed["error_data"] == {
        "details": "QwenPaw runtime failed",
    }, observed
    assert observed["exit_code"] == 0, observed


@pytest.mark.integration
async def test_subprocess_normal_prompt_exits_zero(tmp_path):
    observed = await _prompt_via_subprocess("ok", tmp_path)

    assert observed["prompt_error"] is None, observed
    assert observed["stop_reason"] == "end_turn", observed
    assert observed["exit_code"] == 0, observed


@pytest.mark.integration
async def test_subprocess_internal_error_keeps_request_error(tmp_path):
    """Internal bugs must reach the client as -32603, not as a normal turn.

    A RequestError is handled by the JSON-RPC layer, so the process can still
    exit 0 after the transport closes. The error response itself is the
    evidence that the failure was not converted to ``end_turn``.
    """

    observed = await _prompt_via_subprocess("internal", tmp_path)

    assert observed["stop_reason"] is None, observed
    assert observed["error_code"] == -32603, observed
    assert observed["error_data"] == {
        "details": "QwenPaw runtime failed",
    }, observed
    assert "secret-token" not in str(observed["client_updates"]), observed
    assert "secret-token" not in str(observed["error_data"]), observed
    # RequestError is returned at the JSON-RPC layer; exit 0 is expected and
    # is not the evidence that the internal error was preserved.
    assert observed["exit_code"] == 0, observed


@pytest.mark.integration
async def test_subprocess_pipe_close_runs_shutdown_and_exits_zero(tmp_path):
    """Closing the real ACP pipe must run cleanup and exit cleanly."""

    marker = tmp_path / "shutdown.marker"
    env = _driver_env("ok", tmp_path)
    env["QWENPAW_FAULT_MARKER"] = str(marker)

    async with spawn_agent_process(
        _SubprocessClient(),
        sys.executable,
        str(DRIVER),
        env=env,
        cwd=str(pathlib.Path(__file__).resolve().parents[2]),
    ) as (conn, process):
        await conn.initialize(protocol_version=PROTOCOL_VERSION)
        session = await conn.new_session(cwd=str(tmp_path))
        assert session.session_id

    assert process.returncode == 0
    assert marker.read_text(encoding="utf-8") == "shutdown"


@pytest.mark.integration
async def test_subprocess_active_prompt_pipe_close_exits(tmp_path):
    """Closing the pipe during an active prompt must cancel and clean up."""

    marker = tmp_path / "shutdown.marker"
    env = _driver_env("hang", tmp_path)
    env["QWENPAW_FAULT_MARKER"] = str(marker)
    client = _SubprocessClient()

    async with spawn_agent_process(
        client,
        sys.executable,
        str(DRIVER),
        env=env,
        cwd=str(pathlib.Path(__file__).resolve().parents[2]),
        transport_kwargs={"shutdown_timeout": 5.0},
    ) as (conn, process):
        await conn.initialize(protocol_version=PROTOCOL_VERSION)
        session = await conn.new_session(cwd=str(tmp_path))
        prompt_task = asyncio.create_task(
            conn.prompt(
                prompt=[text_block("hello")],
                session_id=session.session_id,
            ),
        )
        await asyncio.wait_for(client.first_update.wait(), timeout=5)

    with contextlib.suppress(Exception):
        await asyncio.wait_for(prompt_task, timeout=2)

    await asyncio.wait_for(process.wait(), timeout=10)
    assert process.returncode == 0
    assert marker.read_text(encoding="utf-8") == "shutdown"


@pytest.mark.integration
async def test_subprocess_bidirectional_pipe_close_exits_cleanly(tmp_path):
    """Closing both client pipe directions must not fail the final flush."""

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

        # The client closes both directions: agent stdin and agent stdout.
        process.stdin.close()
        with contextlib.suppress(Exception):
            await process.stdin.wait_closed()
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

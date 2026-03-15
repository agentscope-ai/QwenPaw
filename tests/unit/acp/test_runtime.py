# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from copaw.acp.config import ACPHarnessConfig
from copaw.acp.runtime import ACPRuntime
from copaw.acp.transport import JSONRPCNotification, JSONRPCRequest, JSONRPCResponse


@pytest.mark.asyncio
async def test_runtime_logs_unsupported_client_requests(monkeypatch) -> None:
    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )

    sent_errors: list[tuple[str | int, int, str]] = []

    async def fake_send_error(request_id, *, code, message) -> None:
        sent_errors.append((request_id, code, message))

    runtime.transport.send_error = fake_send_error  # type: ignore[method-assign]

    events = []

    async def on_event(event) -> None:
        events.append(event)

    async def permission_handler(payload) -> dict:
        _ = payload
        return {"outcome": "approved"}

    warnings: list[tuple[object, ...]] = []

    def fake_warning(*args) -> None:
        warnings.append(args)

    monkeypatch.setattr("copaw.acp.runtime.logger.warning", fake_warning)

    await runtime._handle_request(  # pylint: disable=protected-access
        chat_id="chat-1",
        session_id="sess-1",
        request=JSONRPCRequest(
            id="req-1",
            method="workspace/list",
            params={"path": "."},
        ),
        permission_handler=permission_handler,
        on_event=on_event,
    )

    assert sent_errors == [
        ("req-1", -32601, "Unsupported ACP client request: workspace/list"),
    ]
    assert events == []
    assert warnings
    assert warnings[0][0] == "Unsupported ACP client request from %s: method=%s params=%s"
    assert warnings[0][1:] == ("opencode", "workspace/list", {"path": "."})


class _BrokenStdin:
    def close(self) -> None:
        raise RuntimeError("boom")

    async def wait_closed(self) -> None:
        return None


class _FakeProcess:
    def __init__(self) -> None:
        self.stdin = _BrokenStdin()
        self.returncode = None
        self.terminated = False
        self.waited = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    async def wait(self) -> int:
        self.waited = True
        return 0


class _EOFStream:
    async def readline(self) -> bytes:
        return b""


@pytest.mark.asyncio
async def test_transport_close_ignores_stdin_close_errors() -> None:
    from copaw.acp.transport import ACPTransport

    transport = ACPTransport(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )
    fake_process = _FakeProcess()
    transport._process = fake_process  # pylint: disable=protected-access

    await transport.close()

    assert fake_process.terminated is True
    assert fake_process.waited is True
    assert transport._process is None  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_transport_start_uses_large_stdio_limit(monkeypatch) -> None:
    from copaw.acp.transport import ACPTransport

    captured: dict[str, object] = {}

    class _SpawnedProcess:
        def __init__(self) -> None:
            self.stdin = None
            self.stdout = _EOFStream()
            self.stderr = _EOFStream()
            self.returncode = 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _SpawnedProcess()

    monkeypatch.setattr(
        "copaw.acp.transport.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    transport = ACPTransport(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )

    await transport.start(cwd=".")
    await asyncio.sleep(0)

    assert captured["args"] == ("npx", "demo")
    assert captured["kwargs"]["limit"] == ACPTransport.STDIO_STREAM_LIMIT


@pytest.mark.asyncio
async def test_transport_reader_failure_fails_pending_requests() -> None:
    from copaw.acp.errors import ACPTransportError
    from copaw.acp.transport import ACPTransport

    transport = ACPTransport(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )
    future = asyncio.get_running_loop().create_future()
    transport._pending["req-1"] = future  # pylint: disable=protected-access

    async def boom() -> None:
        raise RuntimeError("stdout exploded")

    task = asyncio.create_task(boom())
    await asyncio.sleep(0)

    transport._on_reader_task_done("stdout", task)  # pylint: disable=protected-access

    with pytest.raises(
        ACPTransportError,
        match="ACP harness opencode stdout reader failed: stdout exploded",
    ):
        await future

    assert transport._pending == {}  # pylint: disable=protected-access


def test_runtime_normalizes_opencode_tool_update_payload() -> None:
    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )

    payload = runtime._normalize_payload(  # pylint: disable=protected-access
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "tool-1",
            "title": "bash",
            "rawInput": {"command": "rg TODO"},
            "content": [
                {
                    "type": "content",
                    "content": {
                        "type": "text",
                        "text": "found 3 matches",
                    },
                }
            ],
            "rawOutput": {"output": "found 3 matches"},
            "status": "completed",
        },
    )

    assert payload["id"] == "tool-1"
    assert payload["name"] == "bash"
    assert payload["input"] == {"command": "rg TODO"}
    assert payload["output"] == "found 3 matches"


@pytest.mark.asyncio
async def test_runtime_prompt_drains_late_notifications_after_prompt_completion() -> None:
    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )

    events = []

    async def on_event(event) -> None:
        events.append(event)

    async def permission_handler(payload) -> dict:
        _ = payload
        return {"outcome": "approved"}

    async def fake_send_request(method, params, *, timeout=0):  # type: ignore[override]
        _ = method, params, timeout

        async def publish_late_chunk() -> None:
            await asyncio.sleep(0.05)
            await runtime.transport.incoming.put(
                JSONRPCNotification(
                    method="session/update",
                    params={
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "late result"},
                        }
                    },
                ),
            )

        asyncio.create_task(publish_late_chunk())
        await asyncio.sleep(0.01)
        return JSONRPCResponse(id="req-1", result={"stopReason": "end_turn"})

    runtime.transport.send_request = fake_send_request  # type: ignore[method-assign]

    await runtime.prompt(
        chat_id="chat-1",
        session_id="sess-1",
        prompt_blocks=[{"type": "text", "text": "status"}],
        permission_handler=permission_handler,
        on_event=on_event,
    )

    assert [event.type for event in events] == ["assistant_chunk", "run_finished"]
    assert events[0].payload["text"] == "late result"

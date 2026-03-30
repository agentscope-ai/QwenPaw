# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from copaw.acp.config import ACPHarnessConfig
from copaw.acp.permissions import ACPPermissionAdapter
from copaw.acp.runtime import ACPRuntime
from copaw.acp.transport import (
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from copaw.security.tool_guard.approval import ApprovalDecision


class _ApprovalServiceFactory:
    def __init__(self, create_pending) -> None:
        self.create_pending = staticmethod(create_pending)


@pytest.mark.asyncio
async def test_runtime_logs_unsupported_client_requests(monkeypatch) -> None:
    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )

    sent_errors: list[tuple[str | int, int, str]] = []

    async def fake_send_error(request_id, *, code, message) -> None:
        sent_errors.append((request_id, code, message))

    runtime.transport.send_error = (  # type: ignore[method-assign]
        fake_send_error
    )

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
    assert not events
    assert warnings
    assert (
        warnings[0][0]
        == "Unsupported ACP client request from %s: method=%s params=%s"
    )
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
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["limit"] == ACPTransport.STDIO_STREAM_LIMIT


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

    transport._on_reader_task_done(  # pylint: disable=protected-access
        "stdout",
        task,
    )

    with pytest.raises(
        ACPTransportError,
        match="ACP harness opencode stdout reader failed: stdout exploded",
    ):
        await future

    assert not transport._pending  # pylint: disable=protected-access


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
                },
            ],
            "rawOutput": {"output": "found 3 matches"},
            "status": "completed",
        },
    )

    assert payload["id"] == "tool-1"
    assert payload["name"] == "bash"
    assert payload["input"] == {"command": "rg TODO"}
    assert payload["output"] == "found 3 matches"


def test_runtime_backfills_opencode_read_path_from_output() -> None:
    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )

    payload = runtime._normalize_payload(  # pylint: disable=protected-access
        {
            "sessionUpdate": "tool_call_end",
            "toolCallId": "tool-1",
            "name": "read",
            "status": "completed",
            "rawInput": {},
            "rawOutput": {
                "output": (
                    "<path>/tmp/demo/README.md</path>\n"
                    "<content>Hello</content>"
                ),
            },
        },
    )

    assert payload["input"] == {"path": "/tmp/demo/README.md"}
    assert payload["output"] == (
        "<path>/tmp/demo/README.md</path>\n<content>Hello</content>"
    )


def test_runtime_allows_preapproved_dangerous_tool() -> None:
    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )
    # pylint: disable=protected-access
    runtime._require_approval = True  # pylint: disable=protected-access
    runtime._preapproved = True

    assert (
        runtime._should_block_unapproved_tool(
            {"name": "write", "kind": "write"},
        )
        is False
    )


@pytest.mark.asyncio
async def test_runtime_new_session_sends_empty_mcp_servers() -> None:
    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )
    captured: dict[str, object] = {}

    async def fake_send_request(method, params, *, timeout=0):
        captured["method"] = method
        captured["params"] = params
        captured["timeout"] = timeout
        return JSONRPCResponse(id="req-1", result={"sessionId": "sess-1"})

    runtime.transport.send_request = (  # type: ignore[method-assign]
        fake_send_request
    )

    session_id = await runtime.new_session("/tmp/workspace")

    assert session_id == "sess-1"
    assert captured["method"] == "session/new"
    assert captured["params"] == {
        "cwd": "/tmp/workspace",
        "mcpServers": [],
    }


@pytest.mark.asyncio
async def test_runtime_load_session_sends_empty_mcp_servers() -> None:
    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )
    captured: dict[str, object] = {}

    async def fake_send_request(method, params, *, timeout=0):
        captured["method"] = method
        captured["params"] = params
        captured["timeout"] = timeout
        return JSONRPCResponse(id="req-1", result={"sessionId": "sess-1"})

    runtime.transport.send_request = (  # type: ignore[method-assign]
        fake_send_request
    )

    session_id = await runtime.load_session("sess-0", "/tmp/workspace")

    assert session_id == "sess-1"
    assert captured["method"] == "session/load"
    assert captured["params"] == {
        "sessionId": "sess-0",
        "cwd": "/tmp/workspace",
        "mcpServers": [],
    }


@pytest.mark.asyncio
async def test_runtime_prompt_drains_late_notifications() -> None:
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

    async def fake_send_request(  # type: ignore[override]
        method,
        params,
        *,
        timeout=0,
    ):
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
                        },
                    },
                ),
            )

        asyncio.create_task(publish_late_chunk())
        await asyncio.sleep(0.01)
        return JSONRPCResponse(id="req-1", result={"stopReason": "end_turn"})

    runtime.transport.send_request = (  # type: ignore[method-assign]
        fake_send_request
    )

    await runtime.prompt(
        chat_id="chat-1",
        session_id="sess-1",
        prompt_blocks=[{"type": "text", "text": "status"}],
        permission_handler=permission_handler,
        on_event=on_event,
        require_approval=False,
        permission_broker_verified=False,
    )

    assert [event.type for event in events] == [
        "assistant_chunk",
        "run_finished",
    ]
    assert events[0].payload["text"] == "late result"


@pytest.mark.asyncio
async def test_permission_adapter_skips_pending_when_approval_disabled(
    monkeypatch,
) -> None:
    adapter = ACPPermissionAdapter(
        cwd=str(Path.cwd()),
        require_approval=False,
    )

    async def fail_create_pending(**kwargs):
        _ = kwargs
        raise AssertionError("create_pending should not be called")

    monkeypatch.setattr(
        "copaw.acp.permissions.get_approval_service",
        lambda: _ApprovalServiceFactory(fail_create_pending),
    )

    result = await adapter.resolve_permission(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        harness="opencode",
        request_payload={
            "toolCall": {
                "name": "bash",
                "kind": "exec",
                "command": "pwd",
            },
            "options": [{"id": "allow_once", "kind": "allow_once"}],
        },
    )

    assert result.approved is True
    assert result.pending_request_id is None
    assert result.result["outcome"]["outcome"] == "selected"


@pytest.mark.asyncio
async def test_permission_adapter_creates_pending_when_approval_enabled(
    monkeypatch,
) -> None:
    adapter = ACPPermissionAdapter(
        cwd=str(Path.cwd()),
        require_approval=True,
    )
    captured: dict[str, object] = {}
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    future.set_result(ApprovalDecision.APPROVED)

    class _Pending:
        def __init__(self) -> None:
            self.request_id = "req-1"
            self.future = future

    async def fake_create_pending(**kwargs):
        captured.update(kwargs)
        return _Pending()

    monkeypatch.setattr(
        "copaw.acp.permissions.get_approval_service",
        lambda: _ApprovalServiceFactory(fake_create_pending),
    )

    result = await adapter.resolve_permission(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        harness="opencode",
        request_payload={
            "toolCall": {
                "name": "bash",
                "kind": "exec",
                "command": "pwd",
            },
            "options": [{"id": "allow_once", "kind": "allow_once"}],
        },
    )

    assert captured["session_id"] == "session-1"
    assert result.approved is True
    assert result.pending_request_id == "req-1"


@pytest.mark.asyncio
async def test_runtime_cancels_unverified_unsafe_tool_calls() -> None:
    from copaw.acp.errors import ACPTransportError

    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )
    runtime.CANCEL_GRACE_SECONDS = 0.0

    cancel_calls: list[tuple[str, dict[str, str]]] = []
    terminated: list[str] = []
    events = []
    released = asyncio.Event()

    async def on_event(event) -> None:
        events.append(event)

    async def permission_handler(payload) -> dict:
        _ = payload
        return {"outcome": "approved"}

    async def fake_send_notification(method, params) -> None:
        cancel_calls.append((method, params))

    async def fake_terminate_with_error(message: str) -> None:
        terminated.append(message)
        released.set()

    async def fake_send_request(method, params, *, timeout=0):
        _ = params, timeout
        if method != "session/prompt":
            return JSONRPCResponse(id="req-1", result={})
        await runtime.transport.incoming.put(
            JSONRPCNotification(
                method="session/update",
                params={
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCall": {
                            "id": "tool-1",
                            "name": "write",
                            "input": {"filePath": "note.txt"},
                        },
                    },
                },
            ),
        )
        await released.wait()
        raise ACPTransportError(terminated[-1])

    runtime.transport.send_notification = (  # type: ignore[method-assign]
        fake_send_notification
    )
    runtime.transport.terminate_with_error = (  # type: ignore[method-assign]
        fake_terminate_with_error
    )
    runtime.transport.send_request = (  # type: ignore[method-assign]
        fake_send_request
    )
    runtime.transport.is_running = lambda: True  # type: ignore[method-assign]

    await runtime.prompt(
        chat_id="chat-1",
        session_id="sess-1",
        prompt_blocks=[{"type": "text", "text": "inspect project"}],
        permission_handler=permission_handler,
        on_event=on_event,
        require_approval=True,
        permission_broker_verified=False,
    )

    assert cancel_calls == [("session/cancel", {"sessionId": "sess-1"})]
    assert terminated
    assert [event.type for event in events] == ["error", "run_finished"]


@pytest.mark.asyncio
async def test_runtime_cancels_verified_unsafe_tool_without_prompt():
    from copaw.acp.errors import ACPTransportError

    runtime = ACPRuntime(
        "opencode",
        ACPHarnessConfig(enabled=True, command="npx", args=["demo"]),
    )
    runtime.CANCEL_GRACE_SECONDS = 0.0

    cancel_calls: list[tuple[str, dict[str, str]]] = []
    terminated: list[str] = []
    events = []
    released = asyncio.Event()

    async def on_event(event) -> None:
        events.append(event)

    async def permission_handler(payload) -> dict:
        _ = payload
        return {"outcome": "approved"}

    async def fake_send_notification(method, params) -> None:
        cancel_calls.append((method, params))

    async def fake_terminate_with_error(message: str) -> None:
        terminated.append(message)
        released.set()

    async def fake_send_request(method, params, *, timeout=0):
        _ = params, timeout
        if method != "session/prompt":
            return JSONRPCResponse(id="req-1", result={})
        await runtime.transport.incoming.put(
            JSONRPCNotification(
                method="session/update",
                params={
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCall": {
                            "id": "tool-1",
                            "name": "write",
                            "input": {"filePath": "note.txt"},
                        },
                    },
                },
            ),
        )
        await released.wait()
        raise ACPTransportError(terminated[-1])

    runtime.transport.send_notification = (  # type: ignore[method-assign]
        fake_send_notification
    )
    runtime.transport.terminate_with_error = (  # type: ignore[method-assign]
        fake_terminate_with_error
    )
    runtime.transport.send_request = (  # type: ignore[method-assign]
        fake_send_request
    )
    runtime.transport.is_running = lambda: True  # type: ignore[method-assign]

    await runtime.prompt(
        chat_id="chat-1",
        session_id="sess-1",
        prompt_blocks=[{"type": "text", "text": "inspect project"}],
        permission_handler=permission_handler,
        on_event=on_event,
        require_approval=True,
        permission_broker_verified=True,
    )

    assert cancel_calls == [("session/cancel", {"sessionId": "sess-1"})]
    assert terminated
    assert [event.type for event in events] == ["error", "run_finished"]

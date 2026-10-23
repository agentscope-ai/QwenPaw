# -*- coding: utf-8 -*-
"""Tests for CH-0-004 bidirectional JSON-RPC dispatch."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
from collections.abc import Awaitable, Callable

import pytest

from qwenpaw.channel_protocol import (
    ProtocolValidationError,
    RpcError,
    RpcLimits,
    RpcPeer,
    RpcTimeoutError,
)


class MemoryTransport:
    """Small in-memory full-duplex transport for protocol tests."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[str | None] = asyncio.Queue()
        self.peer: MemoryTransport | None = None
        self.closed = False

    async def send(
        self,
        message: str,
        *,
        prepare_write: Callable[[], str | Awaitable[str]] | None = None,
        on_write_succeeded: Callable[[], None] | None = None,
        on_write_failed: Callable[[], None] | None = None,
        on_write_deferred: Callable[[], None] | None = None,
    ) -> None:
        """Deliver one complete framed message to the peer."""
        _ = on_write_failed, on_write_deferred
        if self.closed or self.peer is None or self.peer.closed:
            raise ConnectionError("transport closed")
        if prepare_write is not None:
            message = prepare_write()
            if inspect.isawaitable(message):
                message = await message
        self.peer.inbox.put_nowait(message)
        if on_write_succeeded is not None:
            on_write_succeeded()

    async def receive(self) -> str:
        """Receive one complete framed message."""
        message = await self.inbox.get()
        if message is None:
            raise ConnectionError("transport closed")
        return message

    async def aclose(self) -> None:
        """Close this side and wake its peer."""
        if self.closed:
            return
        self.closed = True
        if self.peer is not None:
            await self.peer.inbox.put(None)


class BlockingCloseTransport(MemoryTransport):
    """Hold transport shutdown until a test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_calls = 0

    async def aclose(self) -> None:
        """Record one close attempt and wait for explicit release."""
        self.close_calls += 1
        self.close_started.set()
        await self.close_release.wait()
        await super().aclose()


def _transport_pair() -> tuple[MemoryTransport, MemoryTransport]:
    """Create two linked memory transports."""
    left = MemoryTransport()
    right = MemoryTransport()
    left.peer = right
    right.peer = left
    return left, right


@pytest.mark.asyncio
async def test_nested_bidirectional_calls_and_out_of_order_responses() -> None:
    """Handlers can call back while the reader continues matching responses."""
    left_transport, right_transport = _transport_pair()
    core = RpcPeer(left_transport)
    runner = RpcPeer(right_transport)

    async def runner_inner(params: object, _: object) -> dict[str, object]:
        """Answer the nested request."""
        assert params == {"value": 2}
        return {"value": 3}

    async def core_outer(_: object, __: object) -> dict[str, object]:
        """Issue a reverse request from inside a request handler."""
        result = await core.call("runner.inner", {"value": 2})
        return {"nested": result["value"]}

    runner.register_method("runner.inner", runner_inner)
    core.register_method("core.outer", core_outer)
    await asyncio.gather(core.start(), runner.start())

    result = await runner.call("core.outer")
    assert result == {"nested": 3}
    await asyncio.gather(core.aclose(), runner.aclose())


@pytest.mark.asyncio
async def test_unknown_method_and_duplicate_response() -> None:
    """Unknown methods error and late responses are ignored."""
    left_transport, right_transport = _transport_pair()
    core = RpcPeer(left_transport)
    runner = RpcPeer(right_transport)
    await asyncio.gather(core.start(), runner.start())

    with pytest.raises(RpcError) as exc_info:
        await core.call("missing.method")
    assert exc_info.value.code == -32601

    await right_transport.send(
        '{"jsonrpc":"2.0","id":"rpc-999","result":null}',
    )
    await asyncio.sleep(0.05)
    assert core.duplicate_responses == 1
    await asyncio.gather(core.aclose(), runner.aclose())


@pytest.mark.asyncio
async def test_null_id_error_never_resolves_a_pending_request() -> None:
    """An uncorrelated JSON-RPC error cannot complete a normal call."""
    left_transport, right_transport = _transport_pair()
    core = RpcPeer(left_transport)
    runner = RpcPeer(right_transport)
    started = asyncio.Event()

    async def never_respond(_: object, __: object) -> None:
        """Keep one correlated request pending for the null-ID response."""
        started.set()
        await asyncio.Future()

    runner.register_method("never.respond", never_respond)
    await asyncio.gather(core.start(), runner.start())
    pending = asyncio.create_task(core.call("never.respond", timeout=1.0))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await right_transport.send(
        '{"jsonrpc":"2.0","id":null,"error":'
        '{"code":-32700,"message":"Parse error"}}',
    )
    await asyncio.sleep(0)
    assert not pending.done()
    assert core.duplicate_responses == 1
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.gather(core.aclose(), runner.aclose())


@pytest.mark.asyncio
async def test_pending_limit_timeout_and_cancel_notification() -> None:
    """The peer bounds pending calls and emits cancellation on timeout."""
    left_transport, right_transport = _transport_pair()
    core = RpcPeer(
        left_transport,
        limits=RpcLimits(max_pending_requests=1, request_timeout=0.5),
    )
    runner = RpcPeer(right_transport)
    cancellation_received = asyncio.Event()
    request_started = asyncio.Event()

    async def never_respond(_: object, __: object) -> None:
        """Keep one request pending until the caller timeout."""
        request_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancellation_received.set()
            raise

    runner.register_method("never.respond", never_respond)
    await asyncio.gather(core.start(), runner.start())

    pending = asyncio.create_task(core.call("never.respond"))
    await asyncio.wait_for(request_started.wait(), timeout=1.0)
    with pytest.raises(RpcError) as limit_error:
        await core.call("second")
    assert limit_error.value.data == {
        "reason_code": "RPC_BACKPRESSURE",
        "retryable": True,
    }
    with pytest.raises(RpcTimeoutError):
        await pending
    await asyncio.wait_for(cancellation_received.wait(), timeout=1.0)
    await asyncio.gather(core.aclose(), runner.aclose())


@pytest.mark.asyncio
async def test_explicit_cancel_notification_cancels_incoming_request() -> None:
    """A caller can explicitly cancel a running request."""
    left_transport, right_transport = _transport_pair()
    core = RpcPeer(left_transport)
    runner = RpcPeer(right_transport)
    cancelled = asyncio.Event()
    started = asyncio.Event()

    async def never_respond(_: object, __: object) -> None:
        """Keep the inbound request running until cancellation."""
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runner.register_method("never.respond", never_respond)
    await asyncio.gather(core.start(), runner.start())
    request = asyncio.create_task(
        core.call("never.respond", timeout=1.0),
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await core.notify(
        "request.cancel",
        {"request_id": "rpc-1", "reason": "user_cancelled"},
    )
    await asyncio.wait_for(cancelled.wait(), timeout=1.0)
    with pytest.raises(RpcError) as cancelled_error:
        await request
    assert cancelled_error.value.data["reason_code"] == "REQUEST_CANCELLED"
    await asyncio.gather(core.aclose(), runner.aclose())


@pytest.mark.asyncio
async def test_late_cancel_does_not_cancel_reverse_pending_request() -> None:
    """Cancel only targets the current inbound request ID owner."""
    left_transport, right_transport = _transport_pair()
    left = RpcPeer(left_transport)
    right = RpcPeer(right_transport)
    reverse_started = asyncio.Event()
    reverse_release = asyncio.Event()

    async def completed(_: object, __: object) -> str:
        """Complete the first inbound owner of rpc-1."""
        return "completed"

    async def reverse(_: object, __: object) -> str:
        """Hold the unrelated reverse rpc-1 request pending."""
        reverse_started.set()
        await reverse_release.wait()
        return "reverse"

    left.register_method("left.completed", completed)
    right.register_method("right.reverse", reverse)
    await asyncio.gather(left.start(), right.start())

    assert await right.call("left.completed") == "completed"
    await asyncio.sleep(0)
    reverse_call = asyncio.create_task(left.call("right.reverse"))
    await asyncio.wait_for(reverse_started.wait(), timeout=1.0)
    await right.notify(
        "request.cancel",
        {"request_id": "rpc-1", "reason": "late"},
    )
    await asyncio.sleep(0)
    assert not reverse_call.done()

    reverse_release.set()
    assert await reverse_call == "reverse"
    await asyncio.gather(left.aclose(), right.aclose())


@pytest.mark.asyncio
async def test_incoming_request_limit_rejects_before_handler() -> None:
    """Inbound backpressure does not start a second request handler."""
    client_transport, server_transport = _transport_pair()
    server = RpcPeer(
        server_transport,
        limits=RpcLimits(max_incoming_requests=1),
    )
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def blocking(_: object, __: object) -> dict[str, int]:
        """Hold the sole inbound request slot."""
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"calls": calls}

    server.register_method("blocking", blocking)
    await server.start()
    await client_transport.send(
        '{"jsonrpc":"2.0","id":"first","method":"blocking"}',
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await client_transport.send(
        '{"jsonrpc":"2.0","id":"second","method":"blocking"}',
    )
    overloaded = json.loads(await client_transport.receive())
    assert overloaded["id"] == "second"
    assert overloaded["error"] == {
        "code": -32021,
        "message": "incoming request limit reached",
        "data": {
            "reason_code": "RPC_BACKPRESSURE",
            "retryable": True,
        },
    }
    assert calls == 1
    release.set()
    completed = json.loads(await client_transport.receive())
    assert completed["id"] == "first"
    await server.aclose()


@pytest.mark.asyncio
async def test_duplicate_id_preserves_owner_and_can_be_reused() -> None:
    """Duplicate IDs cannot replace the active owner or its cancellation."""
    client_transport, server_transport = _transport_pair()
    server = RpcPeer(server_transport)
    started = asyncio.Event()
    calls = 0

    async def controlled(_: object, __: object) -> dict[str, int]:
        """Block the first owner and let a later reused ID finish."""
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await asyncio.Future()
        return {"calls": calls}

    server.register_method("controlled", controlled)
    await server.start()
    request = '{"jsonrpc":"2.0","id":"shared","method":"controlled"}'
    await client_transport.send(request)
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await client_transport.send(request)
    duplicate = json.loads(await client_transport.receive())
    assert duplicate["id"] == "shared"
    assert duplicate["error"]["code"] == -32020
    assert duplicate["error"]["data"] == {
        "reason_code": "RPC_REQUEST_ID_IN_USE",
    }
    assert calls == 1

    await client_transport.send(
        '{"jsonrpc":"2.0","method":"request.cancel",'
        '"params":{"request_id":"shared","reason":"test"}}',
    )
    cancelled = json.loads(await client_transport.receive())
    assert cancelled["id"] == "shared"
    assert cancelled["error"]["data"]["reason_code"] == "REQUEST_CANCELLED"
    await asyncio.sleep(0)

    await client_transport.send(request)
    reused = json.loads(await client_transport.receive())
    assert reused == {
        "jsonrpc": "2.0",
        "id": "shared",
        "result": {"calls": 2},
    }
    await server.aclose()


@pytest.mark.asyncio
async def test_cancel_bypasses_notification_limit_and_reaps_tasks() -> None:
    """Cancel remains available while ordinary notifications are saturated."""
    client_transport, server_transport = _transport_pair()
    server = RpcPeer(
        server_transport,
        limits=RpcLimits(max_notification_tasks=1),
    )
    request_started = asyncio.Event()
    notification_started = asyncio.Event()
    notification_cancelled = asyncio.Event()

    async def request_handler(_: object, __: object) -> None:
        """Wait until the direct cancel path stops the request."""
        request_started.set()
        await asyncio.Future()

    async def notification_handler(_: object, __: object) -> None:
        """Occupy the notification slot until peer shutdown."""
        notification_started.set()
        try:
            await asyncio.Future()
        finally:
            notification_cancelled.set()

    server.register_method("blocking", request_handler)
    server.register_notification("ordinary", notification_handler)
    await server.start()
    await client_transport.send(
        '{"jsonrpc":"2.0","id":"request-1","method":"blocking"}',
    )
    await asyncio.wait_for(request_started.wait(), timeout=1.0)
    await client_transport.send(
        '{"jsonrpc":"2.0","method":"ordinary","params":{}}',
    )
    await asyncio.wait_for(notification_started.wait(), timeout=1.0)
    await client_transport.send(
        '{"jsonrpc":"2.0","method":"request.cancel",'
        '"params":{"request_id":"request-1","reason":"test"}}',
    )
    cancelled = json.loads(await client_transport.receive())
    assert cancelled["error"]["data"]["reason_code"] == ("REQUEST_CANCELLED")
    await client_transport.send(
        '{"jsonrpc":"2.0","method":"ordinary","params":{}}',
    )
    await asyncio.sleep(0)
    assert server.dropped_notifications == 1

    await server.aclose()
    await asyncio.wait_for(notification_cancelled.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_cancelled_close_waiter_can_retry_transport_cleanup() -> None:
    """Caller cancellation does not abandon shared transport cleanup."""
    transport = BlockingCloseTransport()
    peer = RpcPeer(transport)
    first_waiter = asyncio.create_task(peer.aclose())
    await asyncio.wait_for(transport.close_started.wait(), timeout=1.0)

    first_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_waiter
    assert peer.is_closed
    assert not transport.closed

    retry = asyncio.create_task(peer.aclose())
    await asyncio.sleep(0)
    assert not retry.done()
    assert transport.close_calls == 1
    transport.close_release.set()
    await retry
    assert transport.closed
    assert transport.close_calls == 1


@pytest.mark.asyncio
async def test_cancelled_close_waiter_does_not_abandon_task_reap() -> None:
    """Caller cancellation cannot cancel bounded handler cleanup."""
    client_transport, server_transport = _transport_pair()
    server = RpcPeer(server_transport)
    handler_started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    handler_release = asyncio.Event()
    handler_stopped = asyncio.Event()

    async def notification(_: object, __: object) -> None:
        """Delay completion after receiving shutdown cancellation."""
        handler_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await handler_release.wait()
        finally:
            handler_stopped.set()

    server.register_notification("blocking", notification)
    await server.start()
    await client_transport.send(
        '{"jsonrpc":"2.0","method":"blocking"}',
    )
    await asyncio.wait_for(handler_started.wait(), timeout=1.0)

    first_waiter = asyncio.create_task(server.aclose())
    await asyncio.wait_for(cancellation_seen.wait(), timeout=1.0)
    first_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_waiter

    retry = asyncio.create_task(server.aclose())
    await asyncio.sleep(0)
    assert not retry.done()
    handler_release.set()
    await retry
    await asyncio.wait_for(handler_stopped.wait(), timeout=1.0)
    assert server_transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_id", "expected_code"),
    [
        ("{", None, -32700),
        ("[]", None, -32600),
        (
            '{"jsonrpc":"2.0","id":null,"method":"echo"}',
            None,
            -32600,
        ),
        (
            '{"jsonrpc":"2.0","id":"","method":"echo"}',
            None,
            -32600,
        ),
        (
            '{"jsonrpc":"2.0","id":"bad","method":1}',
            "bad",
            -32600,
        ),
        (
            '{"jsonrpc":"1.0","method":"echo"}',
            None,
            -32600,
        ),
    ],
)
async def test_jsonrpc_envelope_conformance(
    payload: str,
    expected_id: str | None,
    expected_code: int,
) -> None:
    """Malformed JSON and envelopes retain distinct JSON-RPC errors."""
    client_transport, server_transport = _transport_pair()
    server = RpcPeer(server_transport)
    await server.start()
    await client_transport.send(payload)
    response = json.loads(await client_transport.receive())
    assert response["id"] == expected_id
    assert response["error"]["code"] == expected_code
    await server.aclose()


@pytest.mark.asyncio
async def test_invalid_params_and_notifications_follow_conformance() -> None:
    """Only a valid request receives Invalid params from DTO validation."""
    client_transport, server_transport = _transport_pair()
    server = RpcPeer(server_transport)
    calls = 0

    async def health(_: object, __: object) -> None:
        """Record calls that pass the method DTO validator."""
        nonlocal calls
        calls += 1

    server.register_method("channel.health", health)
    server.register_notification("channel.health", health)
    await server.start()
    await client_transport.send(
        '{"jsonrpc":"2.0","id":"params","method":"channel.health",'
        '"params":{"unexpected":true}}',
    )
    response = json.loads(await client_transport.receive())
    assert response["id"] == "params"
    assert response["error"]["code"] == -32602

    await client_transport.send(
        '{"jsonrpc":"2.0","method":"channel.health",'
        '"params":{"unexpected":true}}',
    )
    await client_transport.send(
        '{"jsonrpc":"2.0","method":"missing.notification"}',
    )
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client_transport.receive(), timeout=0.02)
    assert calls == 0
    await server.aclose()


@pytest.mark.asyncio
async def test_protocol_and_schema_errors_are_stable() -> None:
    """Protocol mismatch and invalid DTOs expose stable reason codes."""
    left_transport, right_transport = _transport_pair()
    core = RpcPeer(left_transport)
    runner = RpcPeer(right_transport)
    runner.register_method("channel.health", lambda params, _: params)
    await asyncio.gather(core.start(), runner.start())
    with pytest.raises(RpcError) as unknown:
        await core.call("missing.method")
    assert unknown.value.data["reason_code"] == "METHOD_NOT_FOUND"
    with pytest.raises(RpcError) as schema_error:
        await core.call("channel.health", {"unexpected": True})
    assert schema_error.value.data["reason_code"] == "SCHEMA_MISMATCH"
    await asyncio.gather(core.aclose(), runner.aclose())


@pytest.mark.asyncio
async def test_rpc_strict_json_rejects_non_finite_values() -> None:
    """RPC serialization and parsing reject non-standard JSON numbers."""
    left_transport, right_transport = _transport_pair()
    core = RpcPeer(left_transport)
    runner = RpcPeer(right_transport)
    handled = False

    async def echo(params: object, _: object) -> object:
        """Record that a strict-invalid request was not dispatched."""
        nonlocal handled
        handled = True
        return params

    runner.register_method("echo", echo)
    await asyncio.gather(core.start(), runner.start())
    with pytest.raises(ProtocolValidationError) as outbound:
        await core.call("echo", {"score": math.inf})
    assert outbound.value.reason_code == "SCHEMA_MISMATCH"
    await asyncio.gather(core.aclose(), runner.aclose())

    input_transport, output_transport = _transport_pair()
    parser = RpcPeer(output_transport)
    parser.register_method("echo", echo)
    await parser.start()
    await input_transport.send(
        '{"jsonrpc":"2.0","id":"bad","method":"echo",'
        '"params":{"score":NaN}}',
    )
    response = json.loads(await input_transport.receive())
    assert response["id"] is None
    assert response["error"]["code"] == -32700
    assert handled is False
    await input_transport.send("not-json")
    response = json.loads(await input_transport.receive())
    assert response["id"] is None
    assert response["error"]["code"] == -32700
    await parser.aclose()

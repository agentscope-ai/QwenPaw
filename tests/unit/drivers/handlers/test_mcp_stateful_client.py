# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the MCP stateful client lifecycle helpers.

Intent
------
``mcp_stateful_client`` runs its entire context-manager lifecycle in a
single background task so enter/exit happen in the same asyncio task
(see the module docstring — cross-task cancel-scope exits leak MCP
subprocesses).  The downside is that the cleanup/error paths
(``close``, ``_wait_for_lifecycle_exit``, ``_reap_lifecycle_task``,
``_clear_lifecycle_state``) are *timing-sensitive*: whether the
``_LIFECYCLE_CLEANUP_TIMEOUT`` branch fires depends on runner load, so
integration coverage of these lines is non-deterministic.

The cleanup/error paths are also timing-sensitive when left to
integration tests alone: whether ``_LIFECYCLE_CLEANUP_TIMEOUT``
branches fire depends on runner load, so integration-only coverage of
those lines is non-deterministic.  These unit tests drive the cleanup
paths deterministically (with a shrunk cleanup timeout) so the lines
are always exercised regardless of CI timing — giving the file stable,
deterministic unit coverage behind the ``fail_under`` gate.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import anyio
import httpx
import pytest
from mcp import ClientSession
from mcp.shared.exceptions import McpError

import qwenpaw.drivers.handlers.mcp_stateful_client as mod
from qwenpaw.drivers.handlers.mcp_stateful_client import (
    HttpStatefulClient,
    StdIOStatefulClient,
    _is_401_error,
    _is_transport_error,
)


def _client() -> HttpStatefulClient:
    """A fresh HTTP client with no I/O performed.

    ``HttpStatefulClient.__init__`` only validates and stores args; it
    does not open connections, so this is safe for unit-testing the
    synchronous and lifecycle helper methods directly.
    """
    return HttpStatefulClient("test-client", "streamable_http", "http://x")


async def _assert_lifecycle_wires_session_timeout(
    client: HttpStatefulClient | StdIOStatefulClient,
    expected_timeout: timedelta,
    monkeypatch,
) -> None:
    """Exercise the real lifecycle while replacing only its I/O boundaries."""
    timeout_not_passed = object()
    observed_timeouts: list[object] = []

    class SessionSpy:
        def __init__(
            self,
            read_stream,
            write_stream,
            read_timeout_seconds=timeout_not_passed,
        ) -> None:
            del read_stream, write_stream
            observed_timeouts.append(read_timeout_seconds)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            del exc_type, exc_value, traceback

        async def initialize(self) -> None:
            return None

    async def setup_transport(_stack):
        return object(), object()

    monkeypatch.setattr(mod, "ClientSession", SessionSpy)
    monkeypatch.setattr(client, "_setup_transport", setup_transport)

    await client.connect(timeout=1)
    try:
        assert observed_timeouts == [expected_timeout]
    finally:
        await client.close(ignore_errors=False)


# ---------------------------------------------------------------------------
# Error classification helpers
# ---------------------------------------------------------------------------


def test_is_transport_error_distinguishes_transport_from_mcp_errors():
    # anyio.ClosedResourceError is in _TRANSPORT_ERRORS when anyio imports.
    assert _is_transport_error(anyio.ClosedResourceError())
    assert _is_transport_error(ConnectionResetError("reset"))
    assert _is_transport_error(EOFError())
    # An MCP-level error (not a transport failure) must NOT classify.
    assert not _is_transport_error(ValueError("not transport"))


def test_is_401_error_detects_plain_http_401():
    req = httpx.Request("GET", "http://x")
    resp = httpx.Response(401, request=req)
    err = httpx.HTTPStatusError("unauthorized", request=req, response=resp)
    assert _is_401_error(err)

    other = httpx.Response(500, request=req)
    err500 = httpx.HTTPStatusError("boom", request=req, response=other)
    assert not _is_401_error(err500)
    assert not _is_401_error(ValueError("not http"))


def test_is_401_error_drills_into_exception_group():
    """401 wrapped in an ExceptionGroup (mcp raises these) must still match."""
    req = httpx.Request("GET", "http://x")
    resp = httpx.Response(401, request=req)
    err401 = httpx.HTTPStatusError("unauthorized", request=req, response=resp)
    group = ExceptionGroup("grpc failures", [ValueError(), err401])
    assert _is_401_error(group)

    clean_group = ExceptionGroup("grpc failures", [ValueError()])
    assert not _is_401_error(clean_group)


# ---------------------------------------------------------------------------
# _validate_connection
# ---------------------------------------------------------------------------


def test_validate_connection_raises_when_disconnected():
    c = _client()
    with pytest.raises(RuntimeError, match="not connected"):
        c._validate_connection()


def test_validate_connection_raises_when_session_missing():
    c = _client()
    c.is_connected = True
    with pytest.raises(RuntimeError, match="session is not initialized"):
        c._validate_connection()


# ---------------------------------------------------------------------------
# _handle_transport_error
# ---------------------------------------------------------------------------


def test_handle_transport_error_noops_for_non_transport_errors():
    """MCP-level errors must not trigger a reconnect."""
    c = _client()
    c.is_connected = True
    c._ready_event.set()
    c._handle_transport_error(ValueError("mcp-level"))
    assert c.is_connected is True
    assert c._ready_event.is_set()


def test_handle_transport_error_marks_disconnected_and_schedules_reload():
    c = _client()
    c.is_connected = True
    c._ready_event.set()
    c._handle_transport_error(anyio.ClosedResourceError())
    assert c.is_connected is False
    assert not c._ready_event.is_set()
    assert c._reload_event.is_set()


def test_handle_transport_error_skips_reload_when_already_stopping():
    c = _client()
    c.is_connected = True
    c._stop_event.set()
    c._handle_transport_error(anyio.ClosedResourceError())
    assert c.is_connected is False
    # Already stopping — do not arm another reload.
    assert not c._reload_event.is_set()


# ---------------------------------------------------------------------------
# _clear_lifecycle_state
# ---------------------------------------------------------------------------


def test_clear_lifecycle_state_resets_when_task_matches():
    c = _client()
    sentinel = object()
    c._lifecycle_task = sentinel  # type: ignore[assignment]
    c.session = "stale"  # type: ignore[assignment]
    c.is_connected = True
    c._ready_event.set()
    c._clear_lifecycle_state(sentinel)
    assert c._lifecycle_task is None
    assert c.session is None
    assert c.is_connected is False
    assert not c._ready_event.is_set()


def test_clear_lifecycle_state_is_noop_when_task_differs():
    """Guards against a stale reaper clearing state for a newer task."""
    c = _client()
    current = object()
    c._lifecycle_task = current  # type: ignore[assignment]
    c.session = "ses"  # type: ignore[assignment]
    c._clear_lifecycle_state(object())  # different task object
    assert c._lifecycle_task is current
    assert c.session == "ses"


# ---------------------------------------------------------------------------
# _wait_for_lifecycle_exit
# ---------------------------------------------------------------------------


async def test_wait_for_lifecycle_exit_fast_path_clears_state():
    c = _client()

    async def quick() -> int:
        return 1

    task = asyncio.create_task(quick())
    await task  # ensure done so asyncio.wait returns it immediately
    c._lifecycle_task = task
    c.session = "ses"  # type: ignore[assignment]
    c.is_connected = True

    await c._wait_for_lifecycle_exit(task)

    assert c._lifecycle_task is None
    assert c.session is None
    assert c.is_connected is False


async def test_wait_for_lifecycle_exit_timeout_spawns_reaper(monkeypatch):
    monkeypatch.setattr(mod, "_LIFECYCLE_CLEANUP_TIMEOUT", 0.05)
    c = _client()

    release = asyncio.Event()

    async def hang() -> None:
        await release.wait()

    task = asyncio.create_task(hang())
    reaper: asyncio.Task | None = None
    mod._LIFECYCLE_REAPERS.clear()
    try:
        await c._wait_for_lifecycle_exit(task)
        # Timed out waiting → a background reaper must be registered.
        assert task in mod._LIFECYCLE_REAPERS
        reaper = mod._LIFECYCLE_REAPERS[task]
    finally:
        release.set()
        task.cancel()
        if reaper is not None:
            await asyncio.wait_for(reaper, timeout=2)
    assert task not in mod._LIFECYCLE_REAPERS


# ---------------------------------------------------------------------------
# Session request timeout wiring
# ---------------------------------------------------------------------------


async def test_http_lifecycle_wires_read_timeout_to_client_session(
    monkeypatch,
):
    client = HttpStatefulClient(
        "http-client",
        "streamable_http",
        "http://x",
        sse_read_timeout=0.25,
    )

    await _assert_lifecycle_wires_session_timeout(
        client,
        timedelta(seconds=0.25),
        monkeypatch,
    )


async def test_stdio_lifecycle_wires_read_timeout_to_client_session(
    monkeypatch,
):
    client = StdIOStatefulClient(
        "stdio-client",
        "unused-command",
        read_timeout_seconds=0.75,
    )

    await _assert_lifecycle_wires_session_timeout(
        client,
        timedelta(seconds=0.75),
        monkeypatch,
    )


async def test_http_lifecycle_preserves_timedelta_read_timeout(monkeypatch):
    configured_timeout = timedelta(seconds=1.25)
    client = HttpStatefulClient(
        "http-client",
        "streamable_http",
        "http://x",
    )
    client.read_timeout_seconds = configured_timeout

    await _assert_lifecycle_wires_session_timeout(
        client,
        configured_timeout,
        monkeypatch,
    )


async def test_real_client_session_times_out_unanswered_request():
    """The MCP SDK converts its session timeout into a terminal error."""
    server_send, client_read = anyio.create_memory_object_stream(1)
    client_write, server_read = anyio.create_memory_object_stream(1)
    request_received = asyncio.Event()

    async def consume_request_without_responding() -> None:
        await server_read.receive()
        request_received.set()

    consumer = asyncio.create_task(consume_request_without_responding())
    try:
        async with ClientSession(
            client_read,
            client_write,
            read_timeout_seconds=timedelta(seconds=0.05),
        ) as session:
            with pytest.raises(McpError):
                await asyncio.wait_for(session.list_tools(), timeout=3)
            await asyncio.wait_for(request_received.wait(), timeout=1)
    finally:
        if not consumer.done():
            consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        for stream in (
            server_send,
            client_read,
            client_write,
            server_read,
        ):
            await stream.aclose()


# ---------------------------------------------------------------------------
# _reap_lifecycle_task
# ---------------------------------------------------------------------------


async def test_reap_retries_when_cleanup_still_pending(monkeypatch):
    """The reaper must warn and re-cancel when the task ignores the first
    cancel long enough to exceed the cleanup timeout."""
    monkeypatch.setattr(mod, "_LIFECYCLE_CLEANUP_TIMEOUT", 0.05)
    c = _client()

    async def stubborn() -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            # Survive the first cancel long enough for the wait to time out
            # and trigger the retry-warning branch, then propagate.
            await asyncio.sleep(0.15)
            raise

    task = asyncio.create_task(stubborn())
    c._lifecycle_task = task
    c.session = "ses"  # type: ignore[assignment]
    c.is_connected = True
    mod._LIFECYCLE_REAPERS.clear()

    await c._reap_lifecycle_task(task)

    assert task.done()
    assert task not in mod._LIFECYCLE_REAPERS
    assert c._lifecycle_task is None
    assert c.is_connected is False


async def test_reap_clears_state_when_task_already_done():
    c = _client()

    async def done() -> int:
        return 1

    task = asyncio.create_task(done())
    await task
    c._lifecycle_task = task
    c.session = "ses"  # type: ignore[assignment]
    c.is_connected = True
    mod._LIFECYCLE_REAPERS[task] = asyncio.create_task(asyncio.sleep(0))

    await c._reap_lifecycle_task(task)

    assert task not in mod._LIFECYCLE_REAPERS
    assert c._lifecycle_task is None


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


async def test_close_raises_when_not_connected_and_no_task():
    c = _client()
    with pytest.raises(RuntimeError, match="not connected"):
        await c.close(ignore_errors=False)


async def test_close_silent_when_not_connected_and_ignoring_errors():
    c = _client()
    await c.close(ignore_errors=True)  # early return, no task to stop
    assert c._lifecycle_task is None


async def test_close_stops_running_lifecycle_task():
    c = _client()
    stop_event = c._stop_event

    async def lifecycle() -> None:
        await stop_event.wait()

    task = asyncio.create_task(lifecycle())
    c._lifecycle_task = task
    c.is_connected = True

    await c.close(ignore_errors=True)

    assert task.done()
    assert c._lifecycle_task is None
    assert c.is_connected is False


async def test_close_swallows_lifecycle_exception_when_ignoring_errors(
    monkeypatch,
):
    c = _client()
    fake_task = asyncio.create_task(asyncio.sleep(100))
    c._lifecycle_task = fake_task
    c.is_connected = True

    async def boom(task: asyncio.Task) -> None:
        raise RuntimeError("cleanup exploded")

    monkeypatch.setattr(c, "_wait_for_lifecycle_exit", boom)
    try:
        # Should log, not raise.
        await c.close(ignore_errors=True)
    finally:
        fake_task.cancel()
        try:
            await fake_task
        except (asyncio.CancelledError, RuntimeError):
            pass


async def test_close_reraises_lifecycle_exception_when_not_ignoring(
    monkeypatch,
):
    c = _client()
    fake_task = asyncio.create_task(asyncio.sleep(100))
    c._lifecycle_task = fake_task
    c.is_connected = True

    async def boom(task: asyncio.Task) -> None:
        raise RuntimeError("cleanup exploded")

    monkeypatch.setattr(c, "_wait_for_lifecycle_exit", boom)
    try:
        with pytest.raises(RuntimeError, match="cleanup exploded"):
            await c.close(ignore_errors=False)
    finally:
        fake_task.cancel()
        try:
            await fake_task
        except (asyncio.CancelledError, RuntimeError):
            pass


# ---------------------------------------------------------------------------
# list_tools / call_tool
# ---------------------------------------------------------------------------


async def test_list_tools_serves_cache_when_disconnected():
    c = _client()
    c._cached_tools = ["cached-tool"]  # type: ignore[list-item]
    # Disconnected, no live task, no session → must fall back to cache so a
    # flaky MCP client doesn't kill the user's turn.
    result = await c.list_tools()
    assert result == ["cached-tool"]


async def test_list_tools_raises_on_cold_start_without_cache():
    c = _client()
    with pytest.raises(RuntimeError, match="not connected"):
        await c.list_tools()


async def test_call_tool_raises_when_disconnected():
    c = _client()
    with pytest.raises(RuntimeError, match="not connected"):
        await c.call_tool("foo")


async def test_call_tool_handles_transport_error_and_marks_disconnected():
    c = _client()
    c.is_connected = True

    class FakeSession:
        async def call_tool(self, name: str, args: dict) -> None:
            raise ConnectionResetError("pipe broke")

    c.session = FakeSession()  # type: ignore[assignment]
    with pytest.raises(ConnectionResetError):
        await c.call_tool("foo", {})
    # _handle_transport_error marked it for reconnect.
    assert c.is_connected is False
    assert c._reload_event.is_set()


# ---------------------------------------------------------------------------
# connect / reload preconditions
# ---------------------------------------------------------------------------


async def test_connect_raises_when_already_connected():
    c = _client()
    c.is_connected = True
    with pytest.raises(RuntimeError, match="already connected"):
        await c.connect()


async def test_reload_raises_when_not_connected():
    c = _client()
    with pytest.raises(RuntimeError, match="not connected"):
        await c.reload()

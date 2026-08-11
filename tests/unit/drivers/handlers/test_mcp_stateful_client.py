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
import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, ErrorData

import qwenpaw.drivers.handlers.mcp_stateful_client as mod
from qwenpaw.drivers.handlers.mcp_stateful_client import (
    HttpStatefulClient,
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


# ---------------------------------------------------------------------------
# Error classification helpers
# ---------------------------------------------------------------------------


def test_is_transport_error_distinguishes_transport_from_mcp_errors():
    # anyio.ClosedResourceError is in _TRANSPORT_ERRORS when anyio imports.
    import anyio

    assert _is_transport_error(anyio.ClosedResourceError())
    assert _is_transport_error(ConnectionResetError("reset"))
    assert _is_transport_error(EOFError())
    # An MCP-level error (not a transport failure) must NOT classify.
    assert not _is_transport_error(ValueError("not transport"))


def test_is_transport_error_recognizes_terminated_mcp_session():
    exc = McpError(ErrorData(code=32600, message="Session terminated"))
    assert _is_transport_error(exc)


def test_is_transport_error_recognizes_closed_mcp_connection():
    exc = McpError(
        ErrorData(code=CONNECTION_CLOSED, message="Connection closed"),
    )
    assert _is_transport_error(exc)


def test_is_transport_error_rejects_mcp_read_timeout():
    exc = McpError(ErrorData(code=408, message="Timed out while waiting"))
    assert not _is_transport_error(exc)


def test_is_transport_error_unwraps_exception_group():
    exc = McpError(
        ErrorData(code=CONNECTION_CLOSED, message="Connection closed"),
    )
    assert _is_transport_error(ExceptionGroup("task group", [exc]))


def test_is_transport_error_handles_mcp_error_without_payload():
    exc = McpError.__new__(McpError)
    assert not _is_transport_error(exc)


def test_is_transport_error_rejects_other_mcp_errors():
    exc = McpError(ErrorData(code=-32602, message="Invalid tool arguments"))
    assert not _is_transport_error(exc)


def test_is_transport_error_rejects_generic_server_error():
    exc = McpError(
        ErrorData(code=CONNECTION_CLOSED, message="Rate limit exceeded"),
    )
    assert not _is_transport_error(exc)


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
    import anyio

    c = _client()
    c.is_connected = True
    c._ready_event.set()
    c._handle_transport_error(anyio.ClosedResourceError())
    assert c.is_connected is False
    assert not c._ready_event.is_set()
    assert c._reload_event.is_set()


def test_handle_transport_error_skips_reload_when_already_stopping():
    import anyio

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


async def test_list_tools_serves_cache_and_reconnects_on_terminated_session():
    c = _client()
    c.is_connected = True
    c._ready_event.set()
    c._cached_tools = ["cached-tool"]  # type: ignore[list-item]

    class TerminatedSession:
        async def list_tools(self):
            raise McpError(
                ErrorData(code=32600, message="Session terminated"),
            )

    c.session = TerminatedSession()  # type: ignore[assignment]

    result = await c.list_tools()

    assert result == ["cached-tool"]
    assert c.is_connected is False
    assert not c._ready_event.is_set()
    assert c._reload_event.is_set()


async def test_list_tools_retries_once_after_terminated_cold_session():
    c = _client()
    c.is_connected = True
    c._ready_event.set()

    class TerminatedSession:
        async def list_tools(self):
            raise McpError(
                ErrorData(code=32600, message="Session terminated"),
            )

    class HealthySession:
        async def list_tools(self):
            return type("Result", (), {"tools": ["fresh-tool"]})()

    c.session = TerminatedSession()  # type: ignore[assignment]

    async def reconnect() -> None:
        await c._reload_event.wait()
        c.session = HealthySession()  # type: ignore[assignment]
        c.is_connected = True
        c._ready_event.set()

    reconnect_task = asyncio.create_task(reconnect())
    try:
        result = await c.list_tools()
    finally:
        await reconnect_task

    assert result == ["fresh-tool"]
    assert c._cached_tools == ["fresh-tool"]


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


async def test_call_tool_does_not_reconnect_for_generic_server_error():
    c = _client()
    c.is_connected = True
    error = McpError(
        ErrorData(code=CONNECTION_CLOSED, message="Rate limit exceeded"),
    )

    class FakeSession:
        async def call_tool(self, name: str, args: dict) -> None:
            raise error

    c.session = FakeSession()  # type: ignore[assignment]
    with pytest.raises(McpError) as exc_info:
        await c.call_tool("foo", {})

    assert exc_info.value is error
    assert c.is_connected is True
    assert not c._reload_event.is_set()


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

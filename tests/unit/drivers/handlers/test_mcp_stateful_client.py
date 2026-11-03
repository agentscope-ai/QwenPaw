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
``_LIFECYCLE_JOIN_TIMEOUT`` branch fires depends on runner load.
These unit tests shrink that timeout so cleanup paths stay deterministic
behind the ``fail_under`` gate.
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


def _arm(c, session) -> None:
    c._session_closed.set()
    c.session, c._session_closed = session, asyncio.Event()
    c.is_connected = True
    c._ready_event.set()


class _Sess:
    def __init__(self, started=None, tools=None, gate=None):
        self._started, self._tools, self._gate = started, tools, gate

    async def list_tools(self, *_a, **_k):
        if self._started:
            self._started.set()
            await (self._gate or asyncio.Event()).wait()
        return type("R", (), {"tools": self._tools})()

    call_tool = list_tools


async def _swap(c, started, session=None):
    await started.wait()
    c._begin_session_teardown()
    await asyncio.sleep(0)
    if session is not None:
        _arm(c, session)


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
    c._handle_transport_error(ValueError("mcp-level"), c.session)
    assert c.is_connected is True
    assert c._ready_event.is_set()


def test_handle_transport_error_marks_disconnected_and_schedules_reload():
    import anyio

    c = _client()
    c.session = object()  # type: ignore[assignment]
    c.is_connected = True
    c._ready_event.set()
    c._handle_transport_error(anyio.ClosedResourceError(), c.session)
    assert not (c.is_connected or c.session) and c._reload_event.is_set()
    c2, live = _client(), object()
    c2.session, c2.is_connected = live, True  # type: ignore[assignment]
    assert c2._handle_transport_error(ConnectionResetError("stale"), object())
    assert c2.session is live and not c2._reload_event.is_set()


def test_handle_transport_error_skips_reload_when_already_stopping():
    import anyio

    c = _client()
    c.is_connected = True
    c._ready_event.set()
    c._stop_event.set()
    c._handle_transport_error(anyio.ClosedResourceError(), c.session)
    assert not c.is_connected and not c._reload_event.is_set()


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
    c._reload_event.set()
    c._cached_tools = ["stale"]  # type: ignore[list-item]
    c._clear_lifecycle_state(sentinel)
    assert c._lifecycle_task is None and c.session is None
    assert not c.is_connected and not c._ready_event.is_set()
    assert c._cached_tools is None and not c._reload_event.is_set()


def test_clear_lifecycle_state_is_noop_when_task_differs():
    """Guards against a stale reaper clearing state for a newer task."""
    c = _client()
    current = object()
    c._lifecycle_task = current  # type: ignore[assignment]
    c.session = "ses"  # type: ignore[assignment]
    c._reload_event.set()
    c._clear_lifecycle_state(object())  # different task object
    assert c._lifecycle_task is current
    assert c.session == "ses" and c._reload_event.is_set()


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
    monkeypatch.setattr(mod, "_LIFECYCLE_JOIN_TIMEOUT", 0.05)
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
    monkeypatch.setattr(mod, "_LIFECYCLE_JOIN_TIMEOUT", 0.05)
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


async def test_list_tools_serves_cache_immediately_while_reconnecting():
    c = _client()
    c._cached_tools = ["cached"]  # type: ignore[list-item]
    c._lifecycle_task = asyncio.create_task(asyncio.Event().wait())
    try:
        got = await asyncio.wait_for(c.list_tools(), timeout=0.2)
        assert got == ["cached"]
    finally:
        c._lifecycle_task.cancel()
        await asyncio.gather(c._lifecycle_task, return_exceptions=True)


async def test_list_tools_returns_cache_immediately_on_failure():
    class S:
        async def list_tools(self):
            raise ConnectionResetError("pipe")

    c = _client()
    _arm(c, S())
    c._cached_tools = ["cached-tool"]  # type: ignore[list-item]
    got = await asyncio.wait_for(c.list_tools(), timeout=0.5)
    assert got == ["cached-tool"]


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
        _arm(c, HealthySession())

    reconnect_task = asyncio.create_task(reconnect())
    try:
        result = await c.list_tools()
    finally:
        await reconnect_task

    assert result == ["fresh-tool"]
    assert c._cached_tools == ["fresh-tool"]


async def test_list_tools_retries_after_session_swap():
    started, c = asyncio.Event(), _client()
    _arm(c, _Sess(started=started))
    c._cached_tools = ["stale"]  # type: ignore[list-item]
    task = asyncio.create_task(_swap(c, started, _Sess(tools=["fresh"])))
    assert await asyncio.wait_for(c.list_tools(), timeout=1) == ["fresh"]
    await task
    assert c._cached_tools == ["fresh"] and not c._reload_event.is_set()


async def test_drain_abandons_stubborn_rpc(monkeypatch):
    monkeypatch.setattr(mod, "_SESSION_RPC_DRAIN_TIMEOUT", 0)
    c, hold = _client(), asyncio.Event()

    async def hung():
        with pytest.raises(asyncio.CancelledError):
            await asyncio.Event().wait()
        await hold.wait()

    c._rpc_tasks.add(t := asyncio.create_task(hung()))
    await c._drain_session_rpcs()
    assert t not in c._rpc_tasks
    hold.set()
    await asyncio.gather(t, return_exceptions=True)


async def _inflight(op, **kw):
    c, started = _client(), asyncio.Event()
    _arm(c, _Sess(started=started, **kw))
    t = asyncio.create_task(op(c))
    await started.wait()
    return c, t


async def test_list_tools_internal_rpc_cancel_retries_same_session():
    gate = asyncio.Event()
    c, t = await _inflight(lambda x: x.list_tools(), gate=gate, tools=["t"])
    next(iter(c._rpc_tasks)).cancel()
    gate.set()
    assert await asyncio.wait_for(t, timeout=1) == ["t"]


async def test_call_tool_internal_rpc_cancel_reports_aborted():
    c, t = await _inflight(lambda x: x.call_tool("foo", {}))
    next(iter(c._rpc_tasks)).cancel()
    with pytest.raises(RuntimeError, match="aborted"):
        await asyncio.wait_for(t, timeout=1)


async def test_list_tools_caller_cancel_never_serves_cache():
    c, t = await _inflight(lambda x: x.list_tools())
    c._cached_tools = ["cached"]  # type: ignore[list-item]
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t


async def test_call_tool_stop_during_request_is_not_connected():
    c, t = await _inflight(lambda x: x.call_tool("foo", {}))
    await c.close()
    with pytest.raises(RuntimeError, match="not connected"):
        await asyncio.wait_for(t, timeout=1)


async def test_list_tools_stop_during_reconnect_is_not_connected(monkeypatch):
    monkeypatch.setattr(mod, "_LIST_TOOLS_RECONNECT_WAIT", 2)

    class S:
        async def list_tools(self):
            raise ConnectionResetError("pipe")

    c = _client()
    _arm(c, S())
    task = asyncio.create_task(c.list_tools())
    await asyncio.wait_for(c._reload_event.wait(), timeout=1)
    c._stop_event.set()
    with pytest.raises(RuntimeError, match="not connected"):
        await asyncio.wait_for(task, timeout=1)


async def test_await_rpc_abort_paths():
    c = _client()
    c._session_closed.set()
    with pytest.raises(mod._SessionGoneError):
        await c._await_rpc(asyncio.sleep(0), c._session_closed)

    async def hang(s):
        s.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.Event().wait()
        raise ConnectionResetError("pipe broke")

    for mode in ("stop", "closed", "rpc", "cancel"):
        c, s = _client(), asyncio.Event()
        h = hang(s) if mode == "cancel" else _Sess(started=s).list_tools()
        t = asyncio.create_task(c._await_rpc(h, c._session_closed))
        await s.wait()
        if mode == "cancel":
            t.cancel()
        elif mode == "stop":
            c._stop_event.set()
        elif mode == "closed":
            c._begin_session_teardown()
            c._abandon_session_rpcs()
        else:
            next(iter(c._rpc_tasks)).cancel()
        expect = (asyncio.CancelledError, mod._SessionGoneError)
        with pytest.raises(expect[mode != "cancel"]):
            await asyncio.wait_for(t, timeout=1)


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
    assert c.is_connected is False and c.session is None
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


async def test_call_tool_aborts_when_session_invalidated_mid_request():
    for nxt, match in ((None, "not connected"), (_Sess(), "replaced")):
        started, c = asyncio.Event(), _client()
        _arm(c, _Sess(started=started))
        t = asyncio.create_task(_swap(c, started, nxt))
        with pytest.raises(RuntimeError, match=match):
            await asyncio.wait_for(c.call_tool("foo", {}), timeout=1)
        await t
        assert not c._reload_event.is_set() and bool(nxt) is c.is_connected


async def test_connect_raises_when_already_connected():
    c = _client()
    c.is_connected = True
    with pytest.raises(RuntimeError, match="already connected"):
        await c.connect()


async def test_reload_raises_when_not_connected():
    c = _client()
    with pytest.raises(RuntimeError, match="not connected"):
        await c.reload()


async def test_lifecycle_cleanup_paths(monkeypatch):
    c, n = _client(), [0]
    c._reload_event.set()
    c._reconnect_delay = 0.0
    started, aexit, allow = (asyncio.Event() for _ in range(3))

    class S:
        async def initialize(self):
            return self

        __aenter__ = initialize

        async def __aexit__(self, *_a):
            aexit.set()

    async def setup(_s):
        n[0] += 1
        if n[0] == 1:
            raise ConnectionError("boom")
        return object(), object()

    drain = [None]

    async def slow_drain():
        drain[0] = asyncio.current_task()
        started.set()
        await allow.wait()

    monkeypatch.setattr(mod, "ClientSession", lambda *_a, **_k: S())
    monkeypatch.setattr(c, "_setup_transport", setup)
    monkeypatch.setattr(c, "_drain_session_rpcs", slow_drain)
    task = asyncio.create_task(c._run_lifecycle())
    await asyncio.wait_for(c._ready_event.wait(), timeout=2)
    assert n[0] == 2 and c.is_connected and not c._reload_event.is_set()
    c._stop_event.set()
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    await asyncio.sleep(0)
    assert drain[0] is not None
    assert not drain[0].done() and not drain[0].cancelled()
    assert not aexit.is_set()
    allow.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert aexit.is_set() and task.cancelled()


async def test_lifecycle_reconnects_after_anyio_taskgroup_failure(
    monkeypatch,
):
    """TaskGroup child ConnectionResetError must reconnect, not exit."""
    import anyio
    from contextlib import asynccontextmanager

    c, setups, fail = _client(), [0], asyncio.Event()

    class S:
        async def initialize(self):
            return self

        __aenter__ = initialize

        async def __aexit__(self, *_a):
            return None

    @asynccontextmanager
    async def boom_transport():
        async def child():
            await fail.wait()
            raise ConnectionResetError("reset")

        async with anyio.create_task_group() as tg:
            tg.start_soon(child)
            yield object(), object()

    async def setup(stack):
        setups[0] += 1
        if setups[0] == 1:
            return await stack.enter_async_context(boom_transport())
        return object(), object()

    monkeypatch.setattr(mod, "ClientSession", lambda *_a, **_k: S())
    monkeypatch.setattr(c, "_setup_transport", setup)
    task = asyncio.create_task(c._run_lifecycle())
    try:
        await asyncio.wait_for(c._ready_event.wait(), timeout=2)
        assert setups[0] == 1 and c.is_connected
        c._reconnect_delay = 0.0
        fail.set()

        async def reconnected():
            while not (setups[0] >= 2 and c.is_connected):
                await asyncio.sleep(0)

        await asyncio.wait_for(reconnected(), timeout=2)
    finally:
        c._stop_event.set()
        await asyncio.wait_for(
            asyncio.gather(task, return_exceptions=True),
            timeout=2,
        )
    assert setups[0] >= 2


async def test_list_tools_cache_survives_anyio_taskgroup_reconnect(
    monkeypatch,
):
    """TaskGroup teardown must keep cache and return it immediately."""
    import anyio
    from contextlib import asynccontextmanager

    c, n, fail, hold = _client(), [0], asyncio.Event(), asyncio.Event()
    c._cached_tools = ["cached"]  # type: ignore[list-item]

    class S:
        async def initialize(self):
            return self

        __aenter__ = initialize

        async def __aexit__(self, *_a):
            return None

    @asynccontextmanager
    async def boom_transport():
        async def child():
            await fail.wait()
            raise ConnectionResetError("reset")

        async with anyio.create_task_group() as tg:
            tg.start_soon(child)
            yield object(), object()

    async def setup(stack):
        n[0] += 1
        if n[0] == 1:
            return await stack.enter_async_context(boom_transport())
        await hold.wait()
        return object(), object()

    monkeypatch.setattr(mod, "ClientSession", lambda *_a, **_k: S())
    monkeypatch.setattr(c, "_setup_transport", setup)
    task = asyncio.create_task(c._run_lifecycle())
    c._lifecycle_task = task
    try:
        await asyncio.wait_for(c._ready_event.wait(), timeout=2)
        c._reconnect_delay = 0.0
        fail.set()
        while c.is_connected:
            await asyncio.sleep(0)
        got = await asyncio.wait_for(c.list_tools(), timeout=0.2)
        assert got == ["cached"]
    finally:
        c._stop_event.set()
        hold.set()
        task.cancel()
        await asyncio.wait_for(
            asyncio.gather(task, return_exceptions=True),
            timeout=2,
        )


async def test_close_wakes_backoff_sleep(monkeypatch):
    """close() must return immediately while reconnect backoff is sleeping."""
    c, n = _client(), [0]

    class S:
        async def initialize(self):
            return self

        __aenter__ = initialize

        async def __aexit__(self, *_a):
            return None

    async def setup(_s):
        n[0] += 1
        if n[0] == 1:
            return object(), object()
        raise ConnectionError("boom")

    monkeypatch.setattr(mod, "ClientSession", lambda *_a, **_k: S())
    monkeypatch.setattr(c, "_setup_transport", setup)
    await c.connect()
    c._reconnect_delay = 30.0
    reload_task = asyncio.create_task(c.reload())
    try:

        async def in_backoff():
            while not (n[0] >= 2 and not c.is_connected):
                await asyncio.sleep(0)

        await asyncio.wait_for(in_backoff(), timeout=2)
        await asyncio.sleep(0)
        await asyncio.wait_for(c.close(), timeout=1)
        assert c._lifecycle_task is None and not c.is_connected
    finally:
        await asyncio.gather(reload_task, return_exceptions=True)

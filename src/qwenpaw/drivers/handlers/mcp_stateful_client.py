# -*- coding: utf-8 -*-
"""MCP stateful clients with proper cross-task lifecycle management.

This module provides drop-in replacements for AgentScope's MCP clients
that solve the CPU leak issue caused by cross-task context manager exits.

The issue occurs when using AgentScope's StatefulClientBase in uvicorn/FastAPI:
- connect() enters AsyncExitStack in task A (e.g., startup event)
- close() exits AsyncExitStack in task B (e.g., reload background task)
- anyio.CancelScope requires enter/exit in the same task
- Error is silently ignored, leaving MCP processes and streams uncleaned

Our solution: Run the entire context manager lifecycle in a single dedicated
background task, using event-based signaling for reload/stop operations.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Literal

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError

logger = logging.getLogger(__name__)

# anyio is a required transitive dependency of the mcp package, so it is
# always available in practice.  The try/except guards against edge cases
# (e.g. partial installs during testing) without making the whole module
# fail to import.
try:
    import anyio as _anyio

    _ANYIO_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
        _anyio.ClosedResourceError,
        _anyio.BrokenResourceError,
    )
except ImportError:
    _anyio = None
    _ANYIO_TRANSPORT_ERRORS = ()

# All exception types that indicate a dead transport — anyio stream errors,
# httpx transport failures, and low-level socket/pipe errors (including stdio
# pipe breaks when an MCP subprocess exits unexpectedly).
_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    *_ANYIO_TRANSPORT_ERRORS,
    httpx.TransportError,
    EOFError,
    ConnectionResetError,
    BrokenPipeError,
)
_TRANSPORT_MCP_MESSAGES = frozenset(
    {"session terminated", "connection closed"},
)

# How long ``list_tools`` waits for an in-flight reconnect before raising.
# Picked to cover typical HTTP MCP reconnect latency (sub-second to ~1s
# in practice) with headroom, while still failing fast enough that a
# permanently-broken client doesn't stall every turn for long.
_LIST_TOOLS_RECONNECT_WAIT: float = 3.0
_SESSION_RPC_DRAIN_TIMEOUT: float = 2.0  # max wait for cancelled RPCs
_LIFECYCLE_JOIN_TIMEOUT = 8.0  # cleanup 5 + drain 2 + slack 1
_LIFECYCLE_REAPERS: dict[asyncio.Task, asyncio.Task] = {}


def _is_transport_error(exc: BaseException) -> bool:
    """Return ``True`` if *exc* indicates a broken or closed transport.

    Transport errors mean the underlying stream is dead; the client should
    reconnect rather than treat the failure as permanent.  See
    ``_TRANSPORT_ERRORS`` for the full list of recognised exception types.
    """
    if isinstance(exc, _TRANSPORT_ERRORS):
        return True

    if isinstance(exc, McpError):
        error = getattr(exc, "error", None)
        message = str(getattr(error, "message", exc)).strip().casefold()
        return message in _TRANSPORT_MCP_MESSAGES

    sub_excs = getattr(exc, "exceptions", None)
    if sub_excs:
        return any(_is_transport_error(item) for item in sub_excs)
    return False


def _is_401_error(exc: BaseException) -> bool:
    """Return True if exc (or any sub-exception) is HTTP 401."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 401
    # ExceptionGroup wraps one or more sub-exceptions (Python 3.11+)
    sub_excs = getattr(exc, "exceptions", None)
    if sub_excs:
        return any(_is_401_error(e) for e in sub_excs)
    return False


def _discard_task_result(task: asyncio.Future[Any]) -> None:
    if task.done() and not task.cancelled():
        task.exception()


def _restore_cancel(task: Any, n: int) -> None:
    """Re-arm *n* cancels. No-op for None/0."""
    if task is None or n <= 0:
        return
    for _ in range(n):
        task.cancel()


class _SessionGoneError(Exception):
    pass


async def _wait_task_uncancelled(task: Any, name: str) -> int:
    """Uncancel until done; return count. Caller restores."""
    current, n = asyncio.current_task(), 0
    while True:
        while current is not None and current.cancelling():
            current.uncancel()
            n += 1
        if task.done():
            break
        try:
            # shield: parent cancel must not cancel the drain/gather child.
            await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if name and not task.cancelled() and (e := task.exception()):
        logger.error("MCP client '%s': cleanup failed: %s", name, e)
    return n


async def _gather_uncancelled(*tasks: Any) -> None:
    """Cancel watchers, wait, restore cancel immediately."""
    for t in tasks:
        t.cancel()
    g = asyncio.gather(*tasks, return_exceptions=True)
    n = await _wait_task_uncancelled(g, "")
    _restore_cancel(asyncio.current_task(), n)


class _MCPClientMixin:
    """Mixin providing shared tool-call and lifecycle logic for both clients.

    ``StdIOStatefulClient`` and ``HttpStatefulClient`` share identical
    ``list_tools``, ``call_tool``, ``close``, ``connect``, ``reload``,
    ``_run_lifecycle``, ``_validate_connection``, and
    ``_handle_transport_error`` implementations.  This mixin is the single
    authoritative source for all of them.

    Subclasses must implement ``_setup_transport`` to establish the
    transport-specific connection and enter it into the provided
    ``AsyncExitStack``.

    Attributes declared below are set by the concrete subclass's
    ``__init__``.  They are listed here (as bare annotations, no assignment)
    so that static type checkers (mypy, pyright) can verify usages inside
    mixin methods without requiring a full Protocol.
    """

    # Attributes provided by the concrete subclass's __init__.
    # Bare annotations (no assignment) have no runtime effect; they exist
    # only so static type checkers can verify usages in mixin methods.
    name: str
    session: ClientSession | None
    is_connected: bool
    is_stateful: bool
    _oauth_required: bool
    _cached_tools: Any
    _stop_event: asyncio.Event
    _reload_event: asyncio.Event
    _ready_event: asyncio.Event
    _session_closed: asyncio.Event
    _rpc_tasks: set[asyncio.Task]
    _lifecycle_task: asyncio.Task | None

    # Exponential backoff & circuit breaker state
    _reconnect_delay: float
    _consecutive_failures: int
    _circuit_open: bool
    _circuit_open_since: float
    _max_reconnect_delay: float
    _circuit_breaker_threshold: int
    _circuit_half_open_after: float

    # ------------------------------------------------------------------
    # Transport hook (implemented by each concrete subclass)
    # ------------------------------------------------------------------

    async def _setup_transport(
        self,
        stack: AsyncExitStack,
    ) -> tuple[Any, Any]:
        """Enter the transport context manager and
         return ``(read, write)`` streams.

        Subclasses enter their transport-specific context manager (e.g.
        ``stdio_client``, ``streamable_http_client``, or ``sse_client``)
        into *stack* and return the two stream objects that
        ``ClientSession`` expects.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _run_lifecycle(self) -> None:  # noqa: C901
        # pylint: disable=too-many-statements
        """Run MCP client lifecycle in a dedicated task.

        This ensures ``__aenter__`` and ``__aexit__`` are called in the
        same asyncio task, avoiding the cross-task cancel-scope error.
        Transport setup is delegated to ``_setup_transport``.
        """
        while not self._stop_event.is_set():
            n, cancelled, current = 0, False, asyncio.current_task()
            try:
                logger.debug(f"Connecting MCP client: {self.name}")

                async with AsyncExitStack() as stack:
                    read_stream, write_stream = await self._setup_transport(
                        stack,
                    )

                    self.session = ClientSession(read_stream, write_stream)
                    await stack.enter_async_context(self.session)
                    await self.session.initialize()

                    self._session_closed = asyncio.Event()
                    self.is_connected = True
                    self._ready_event.set()
                    # Reset backoff & circuit breaker on success
                    self._reconnect_delay = 1.0
                    self._consecutive_failures = 0
                    self._circuit_open = False
                    logger.info(f"MCP client connected: {self.name}")

                    try:
                        await self._wait_pair(
                            self._reload_event,
                            self._stop_event,
                        )
                    except asyncio.CancelledError:
                        cancelled = True
                    finally:
                        self._begin_session_teardown()
                        if self._stop_event.is_set():
                            logger.info(f"Stopping MCP client: {self.name}")
                            self._cached_tools = None
                        else:
                            logger.info(f"Reloading MCP client: {self.name}")
                            self._reload_event.clear()
                        drain = asyncio.create_task(self._drain_session_rpcs())
                        n = await _wait_task_uncancelled(drain, self.name)
                # Restore only after aexit so CancelScope exits this task.
                if cancelled or n:
                    _restore_cancel(current, n)
                    raise asyncio.CancelledError

            except Exception as e:
                # AnyIO TaskGroup failures cancel this task before aexit
                # raises the real transport error. Do not treat that as
                # an external shutdown; follow the reconnect path.
                if self._stop_event.is_set():
                    logger.error(
                        "MCP client '%s' failed during stop: %s",
                        self.name,
                        e,
                    )
                    self._begin_session_teardown()
                    self._abandon_session_rpcs()
                    return
                # 401 means the server requires OAuth; fail fast and signal
                # connect() so it can raise instead of returning silently.
                if _is_401_error(e):
                    logger.info(
                        f"MCP client '{self.name}': server requires OAuth "
                        "(HTTP 401). Authorize via the UI to connect.",
                    )
                    self._oauth_required = True
                    self._stop_event.set()
                    self._begin_session_teardown()
                    self._reload_event.clear()
                    self._abandon_session_rpcs()
                    self._ready_event.set()
                    return
                self._consecutive_failures += 1
                logger.error(
                    f"Error in MCP client lifecycle for {self.name} "
                    f"(failure {self._consecutive_failures}/"
                    f"{self._circuit_breaker_threshold}): {e}",
                    exc_info=True,
                )
                self._begin_session_teardown()
                self._reload_event.clear()
                self._abandon_session_rpcs()

                # Circuit breaker: stop retrying after too many failures
                if (
                    self._consecutive_failures
                    >= self._circuit_breaker_threshold
                ):
                    self._circuit_open = True
                    self._circuit_open_since = time.monotonic()
                    logger.error(
                        "MCP client '%s': circuit breaker OPEN after %d "
                        "consecutive failures. Automatic reconnect "
                        "suspended. Will probe after %.0fs.",
                        self.name,
                        self._consecutive_failures,
                        self._circuit_half_open_after,
                    )
                    # Wait for half-open probe interval or stop signal
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=self._circuit_half_open_after,
                        )
                    except asyncio.TimeoutError:
                        # Half-open: allow one probe attempt
                        logger.info(
                            "MCP client '%s': circuit half-open, "
                            "attempting probe reconnect.",
                            self.name,
                        )
                        self._circuit_open = False
                        self._reconnect_delay = 1.0
                    continue

                # Exponential backoff with jitter
                jittered_delay = self._reconnect_delay * (
                    0.5 + random.random() * 0.5
                )
                logger.info(
                    "MCP client '%s': reconnecting in %.1fs "
                    "(backoff=%.1fs).",
                    self.name,
                    jittered_delay,
                    self._reconnect_delay,
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=jittered_delay,
                    )
                except asyncio.TimeoutError:
                    pass
                # Increase delay for next attempt (capped)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay,
                )

        logger.info(f"MCP client lifecycle task exited: {self.name}")

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect to the MCP server.

        Starts the background lifecycle task and waits until the first
        connection is established.

        Args:
            timeout: Connection timeout in seconds (default 30 s).

        Raises:
            RuntimeError: If already connected.
            asyncio.TimeoutError: If the connection is not established
                within *timeout* seconds.
        """
        has_task = (
            self._lifecycle_task is not None
            and not self._lifecycle_task.done()
        )
        if self.is_connected or has_task:
            raise RuntimeError(
                f"MCP client '{self.name}' is already connected or a "
                f"lifecycle task is still running. "
                f"Call close() before connecting again.",
            )

        # Clear both events: _stop_event so the task does not exit
        # immediately, and _ready_event so the wait below blocks until
        # the *new* connection is established (the event may still be
        # set from a previous connect/close cycle).
        self._stop_event.clear()
        self._oauth_required = False
        self._ready_event.clear()
        # Reset circuit breaker state for fresh connect attempt
        self._reconnect_delay = 1.0
        self._consecutive_failures = 0
        self._circuit_open = False
        self._lifecycle_task = asyncio.create_task(self._run_lifecycle())

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout waiting for MCP client '{self.name}' to connect",
            )
            self._stop_event.set()
            lifecycle_task = self._lifecycle_task
            if lifecycle_task:
                if not lifecycle_task.done():
                    lifecycle_task.cancel()
                await self._wait_for_lifecycle_exit(lifecycle_task)
            raise

        if self._oauth_required:
            raise RuntimeError(
                f"MCP client '{self.name}' requires OAuth authorization "
                "(HTTP 401). Please authorize via the UI before connecting.",
            )

    async def reload(self, timeout: float = 30.0) -> None:
        """Reload the MCP client (tear down and reconnect).

        Args:
            timeout: Reconnection timeout in seconds (default 30 s).

        Raises:
            RuntimeError: If not connected, or if the client is stopped
                while reload is waiting.
            asyncio.TimeoutError: If the new connection is not
                established within *timeout* seconds.
        """
        if not self.is_connected:
            raise self._not_connected_error()

        logger.info(f"Triggering reload for MCP client: {self.name}")
        self._reload_event.set()
        # Clear _ready_event *before* waiting.  When connected,
        # _ready_event is already set; without this clear, the wait
        # below would return immediately before the reload has started.
        self._ready_event.clear()

        await self._wait_ready(timeout)
        if self._stop_event.is_set():
            raise self._not_connected_error()
        if self.is_connected and self._ready_event.is_set():
            logger.info(f"Reload completed for MCP client: {self.name}")
            return
        logger.error(
            f"Timeout waiting for MCP client '{self.name}' to reload",
        )
        raise asyncio.TimeoutError

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_tools(self):  # noqa: C901 pylint: disable=too-many-branches
        """Return all tools available from the MCP server.

        Returns raw MCP ``Tool`` schema objects. Tool wrapping belongs to the
        runtime exposure layer, not the transport client.

        If the client is in a transient reconnect window (``is_connected``
        is False but the lifecycle task is still alive), return cached
        schemas immediately when available.  Otherwise wait briefly for
        the reconnect to finish before raising.  This keeps a single
        flaky MCP client from killing the user's turn — agentscope's
        ``Toolkit.get_tool_schemas`` has no per-client error handling
        and one ``list_tools`` failure aborts the whole schema fetch
        (and thus ``compress_context`` → ``_reply``).

        Returns:
            List of raw MCP Tool objects

        Raises:
            RuntimeError: If not connected and no reconnect is in flight,
                or if the reconnect does not complete within
                ``_LIST_TOOLS_RECONNECT_WAIT`` seconds.
        """
        if self._circuit_open:
            raise self._circuit_open_error()

        gone, last_exc = False, None
        if not self.is_connected:
            has_task = self._lifecycle_task is not None and not (
                self._lifecycle_task.done()
            )
            if has_task and not self._stop_event.is_set():
                cached = self._cached_tools_if_disconnected()
                if cached is not None:
                    logger.warning(
                        "MCP client '%s' not connected; serving cached "
                        "schemas while reconnecting.",
                        self.name,
                    )
                    return cached
                logger.info(
                    "MCP client '%s' not connected; waiting up to %.1fs "
                    "for reconnect before list_tools.",
                    self.name,
                    _LIST_TOOLS_RECONNECT_WAIT,
                )
                await self._wait_ready(_LIST_TOOLS_RECONNECT_WAIT)

        for attempt in (0, 1):
            session, closed = self.session, self._session_closed
            if self._stop_event.is_set() or not (
                self.is_connected and session
            ):
                break
            try:
                res = await self._await_rpc(session.list_tools(), closed)
            except Exception as exc:
                last_exc = exc
                gone = isinstance(exc, _SessionGoneError)
                if not (gone or self._handle_transport_error(exc, session)):
                    raise
                if self._stop_event.is_set():
                    raise self._not_connected_error() from exc
                cached = self._cached_tools_if_disconnected()
                if cached is not None:
                    logger.warning(
                        "MCP client '%s' session failed during list_tools; "
                        "serving cached schemas while reconnecting.",
                        self.name,
                    )
                    return cached
                if attempt == 0:
                    await self._wait_ready(_LIST_TOOLS_RECONNECT_WAIT)
                    if self._stop_event.is_set():
                        raise self._not_connected_error() from exc
                    continue
                break
            self._cached_tools = res.tools
            return res.tools

        cached = self._cached_tools_if_disconnected()
        if cached is not None:
            logger.warning(
                "MCP client '%s' still disconnected after %.1fs; serving "
                "cached schemas from last successful list_tools.",
                self.name,
                _LIST_TOOLS_RECONNECT_WAIT,
            )
            return cached

        if last_exc is not None:
            if gone:
                raise self._rpc_gone_error() from last_exc
            raise last_exc
        raise self._not_connected_error()

    async def call_tool(self, name: str, arguments: dict | None = None):
        """Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments (optional)

        Returns:
            Tool call result

        Raises:
            RuntimeError: If not connected or session was replaced
        """
        self._validate_connection()
        session, closed = self.session, self._session_closed
        if session is None:
            raise self._not_connected_error()
        try:
            coro = session.call_tool(name, arguments or {})
            return await self._await_rpc(coro, closed)
        except Exception as exc:
            # No same-session retry: the server may already have run it.
            if self._stop_event.is_set():
                raise self._not_connected_error() from exc
            if self.session is not session:
                raise self._rpc_gone_error() from exc
            if isinstance(exc, _SessionGoneError):
                raise RuntimeError(
                    f"MCP client '{self.name}' request was aborted.",
                ) from exc
            self._handle_transport_error(exc, session)
            raise

    async def close(self, ignore_errors: bool = True) -> None:
        """Close the MCP client and stop its background lifecycle task.

        Unlike the old guard (``if not self.is_connected: return``), this
        method always attempts to stop the lifecycle task when one is still
        running.  The old guard was a bug: when the client is in a reconnect
        loop (``is_connected=False`` but the task is alive and will spawn a
        new subprocess the moment it wakes from ``asyncio.sleep``), skipping
        the stop leaked the eventual subprocess permanently.

        Args:
            ignore_errors: When ``True`` (default), exceptions during cleanup
                are logged but not re-raised.

        Raises:
            RuntimeError: If not connected and no task is running, and
                ``ignore_errors`` is ``False``.
        """
        has_task = self._lifecycle_task is not None and not (
            self._lifecycle_task.done()
        )

        if not self.is_connected and not has_task:
            if not ignore_errors:
                raise RuntimeError(
                    f"MCP client '{self.name}' is not connected. "
                    f"Call connect() before closing.",
                )
            return

        lifecycle_task = self._lifecycle_task
        try:
            self._stop_event.set()
            if lifecycle_task:
                await self._wait_for_lifecycle_exit(lifecycle_task)
        except Exception as e:
            if not ignore_errors:
                raise
            logger.warning(
                f"Error closing MCP client '{self.name}': {e}",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _begin_session_teardown(self) -> None:
        self.is_connected, self.session = False, None
        self._session_closed.set()
        self._ready_event.clear()

    async def _await_rpc(self, coro: Any, closed: asyncio.Event):
        if closed.is_set() or self._stop_event.is_set():
            coro.close()
            raise _SessionGoneError("session torn down")
        rpc = asyncio.create_task(coro, name=f"mcp-rpc:{self.name}")
        self._rpc_tasks.add(rpc)
        rpc.add_done_callback(self._rpc_tasks.discard)
        watchers = {
            asyncio.create_task(closed.wait()),
            asyncio.create_task(self._stop_event.wait()),
        }
        try:
            done, _ = await asyncio.wait(
                {rpc, *watchers},
                return_when=asyncio.FIRST_COMPLETED,
            )
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise asyncio.CancelledError
            if rpc in done and not rpc.cancelled():
                return rpc.result()
            raise _SessionGoneError("session torn down")
        finally:
            rpc.cancel()
            rpc.add_done_callback(_discard_task_result)
            await _gather_uncancelled(*watchers)  # never wait on hung rpc

    def _abandon_session_rpcs(self, tasks: list[Any] | None = None) -> None:
        pool = tasks if tasks is not None else list(self._rpc_tasks)
        leftover = [task for task in pool if not task.done()]
        if leftover:
            logger.warning(
                f"MCP client '{self.name}': abandoning {len(leftover)} RPCs",
            )
        for task in pool:
            task.cancel()
            task.add_done_callback(_discard_task_result)
            self._rpc_tasks.discard(task)

    async def _drain_session_rpcs(self) -> None:
        await asyncio.sleep(0)
        pending = [t for t in tuple(self._rpc_tasks) if not t.done()]
        if not pending:
            return
        for task in pending:
            task.cancel()
        done, leftover = await asyncio.wait(
            pending,
            timeout=_SESSION_RPC_DRAIN_TIMEOUT,
        )
        for task in done:
            _discard_task_result(task)
        if leftover:
            self._abandon_session_rpcs(list(leftover))

    def _clear_lifecycle_state(self, task: asyncio.Task) -> None:
        """Clear state once the current lifecycle task has exited."""
        if self._lifecycle_task is task:
            self._lifecycle_task = None
            self._begin_session_teardown()
            self._abandon_session_rpcs()
            self._cached_tools = None
            self._reload_event.clear()

    async def _reap_lifecycle_task(self, lifecycle_task: asyncio.Task) -> None:
        """Retain and retry cleanup until the lifecycle task exits."""
        try:
            while not lifecycle_task.done():
                lifecycle_task.cancel()
                done, _ = await asyncio.wait(
                    {lifecycle_task},
                    timeout=_LIFECYCLE_JOIN_TIMEOUT,
                )
                if lifecycle_task not in done:
                    logger.warning(
                        "MCP client '%s' lifecycle cleanup is still pending; "
                        "retrying cancellation: done=%s, cancelled=%s, "
                        "cancelling=%s",
                        self.name,
                        lifecycle_task.done(),
                        lifecycle_task.cancelled(),
                        lifecycle_task.cancelling(),
                    )
            await asyncio.gather(lifecycle_task, return_exceptions=True)
            self._clear_lifecycle_state(lifecycle_task)
        finally:
            _LIFECYCLE_REAPERS.pop(lifecycle_task, None)

    async def _wait_for_lifecycle_exit(self, task: asyncio.Task) -> None:
        """Wait briefly for lifecycle cleanup without blocking forever."""
        done, _ = await asyncio.wait(
            {task},
            timeout=_LIFECYCLE_JOIN_TIMEOUT,
        )
        if task not in done:
            if task not in _LIFECYCLE_REAPERS:
                reaper = asyncio.create_task(
                    self._reap_lifecycle_task(task),
                    name=f"mcp-lifecycle-reaper:{self.name}",
                )
                _LIFECYCLE_REAPERS[task] = reaper
            logger.error(
                "Timed out cleaning up MCP client '%s'; background reaper "
                "active: "
                "done=%s, cancelled=%s, cancelling=%s",
                self.name,
                task.done(),
                task.cancelled(),
                task.cancelling(),
            )
            return

        await asyncio.gather(task, return_exceptions=True)
        self._clear_lifecycle_state(task)

    def _handle_transport_error(self, exc: BaseException, dead: Any) -> bool:
        """Mark the client as disconnected and schedule a reconnect when *exc*
        indicates a transport/stream failure rather than an MCP-level error.

        **HTTP / streamable_http scenario**
        ``streamable_http_client``'s ``post_writer`` background task silently
        closes ``write_stream`` in its ``finally`` block when an internal
        error occurs (e.g. HTTP read timeout after 300 s).  The lifecycle
        loop keeps seeing ``is_connected=True`` because the failure never
        propagates to it.  Without this handler every subsequent
        ``call_tool`` call would raise ``anyio.ClosedResourceError``
        indefinitely — the client would never recover without a process
        restart.

        **StdIO scenario**
        If the MCP subprocess exits unexpectedly, the stdio pipe breaks and
        subsequent ``call_tool`` calls raise ``BrokenPipeError``,
        ``EOFError``, or ``anyio.ClosedResourceError``.  The same handler
        detects these and triggers a reconnect.  For StdIO, reconnecting
        means spawning a *new* subprocess.  The lifecycle task exits the
        current ``AsyncExitStack`` (which terminates the dead/old subprocess)
        and then opens a fresh one, so there is no subprocess accumulation.

        Returns:
            Whether this is a recoverable transport failure.
        """
        if not _is_transport_error(exc):
            return False
        if not self.is_connected or self.session is not dead:
            return True
        logger.warning(
            "Transport error on MCP client '%s' (%s: %s); "
            "marking as disconnected and scheduling reconnect.",
            self.name,
            type(exc).__name__,
            exc,
        )
        self._begin_session_teardown()
        if not self._stop_event.is_set():
            self._reload_event.set()
        return True

    async def _wait_pair(self, a, b, timeout=None):
        pair = [asyncio.create_task(a.wait()), asyncio.create_task(b.wait())]
        try:
            await asyncio.wait(
                pair,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            await _gather_uncancelled(*pair)

    async def _wait_ready(self, timeout: float | None = None) -> None:
        await self._wait_pair(self._ready_event, self._stop_event, timeout)

    def _cached_tools_if_disconnected(self) -> Any:
        if self.is_connected or self._stop_event.is_set():
            return None
        return self._cached_tools

    def _not_connected_error(self) -> RuntimeError:
        return RuntimeError(
            f"MCP client '{self.name}' is not connected. "
            f"Call connect() first.",
        )

    def _circuit_open_error(self) -> RuntimeError:
        return RuntimeError(
            f"MCP client '{self.name}' unavailable (circuit open after "
            f"{self._consecutive_failures} consecutive failures)",
        )

    def _rpc_gone_error(self) -> RuntimeError:
        if self.is_connected and self.session:
            return RuntimeError(
                f"MCP client '{self.name}' session was replaced.",
            )
        return self._not_connected_error()

    def _validate_connection(self) -> None:
        """Raise ``RuntimeError`` if the session is not ready.

        Raises:
            RuntimeError: If not connected or session not initialized
        """
        if self._circuit_open:
            raise self._circuit_open_error()

        if self._stop_event.is_set() or not self.is_connected:
            raise self._not_connected_error()

        if not self.session:
            raise RuntimeError(
                f"MCP client '{self.name}' session is not initialized. "
                f"Call connect() first.",
            )


class StdIOStatefulClient(_MCPClientMixin):
    """StdIO MCP client with proper cross-task lifecycle management.

    Drop-in replacement for agentscope.mcp.StdIOStatefulClient that solves
    the CPU leak issue by running the entire context manager lifecycle in
    a single dedicated background task.

    Key improvements:
    - Context manager enter/exit happens in the same asyncio task
    - Uses event-based signaling for reload/stop operations
    - Properly cleans up MCP subprocess and stdio streams
    - No CPU leak on reload
    - No zombie processes

    API-compatible with agentscope.mcp.StdIOStatefulClient for drop-in
    replacement.
    """

    def __init__(
        self,
        name: Any,
        command: Any,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        encoding: str = "utf-8",
        encoding_error_handler: Literal[
            "strict",
            "ignore",
            "replace",
        ] = "strict",
        read_timeout_seconds: float = 60 * 5,
    ) -> None:
        """Initialize the StdIO MCP client.

        Args:
            name: Client identifier (unique across MCP servers)
            command: The executable to run to start the server
            args: Command line arguments to pass to the executable
            env: The environment to use when spawning the process
            cwd: The working directory to use when spawning the process
            encoding: The text encoding used when sending/receiving messages
            encoding_error_handler: The text encoding error handler
            read_timeout_seconds: The read timeout seconds

        Raises:
            TypeError: If name or command is not a string
        """
        if not isinstance(name, str):
            raise TypeError(f"name must be str, got {type(name).__name__}")
        if not isinstance(command, str):
            raise TypeError(
                f"command must be str, got {type(command).__name__}",
            )

        self.name = name
        self.is_stateful = True
        self.server_params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env,
            cwd=cwd,
            encoding=encoding,
            encoding_error_handler=encoding_error_handler,
        )
        self.read_timeout_seconds = read_timeout_seconds

        # Lifecycle management
        self._lifecycle_task: asyncio.Task | None = None
        self._reload_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._session_closed = asyncio.Event()
        self._rpc_tasks: set[asyncio.Task] = set()
        self._oauth_required = False

        # Exponential backoff & circuit breaker
        self._reconnect_delay: float = 1.0
        self._consecutive_failures: int = 0
        self._circuit_open: bool = False
        self._circuit_open_since: float = 0.0
        self._max_reconnect_delay: float = 60.0
        self._circuit_breaker_threshold: int = 5
        self._circuit_half_open_after: float = 300.0

        # Session state
        self.session: ClientSession | None = None
        self.is_connected = False

        # Tool cache
        self._cached_tools = None

    async def _setup_transport(
        self,
        stack: AsyncExitStack,
    ) -> tuple[Any, Any]:
        # Local import: stdio_client pulls in anyio's subprocess machinery;
        # deferring it here keeps module import time fast and avoids pulling
        # platform-specific code at import time for users who only use HTTP.
        from mcp.client.stdio import stdio_client

        context = await stack.enter_async_context(
            stdio_client(self.server_params),
        )
        return context[0], context[1]


class HttpStatefulClient(_MCPClientMixin):
    """HTTP/SSE MCP client with proper cross-task lifecycle management.

    Drop-in replacement for agentscope.mcp.HttpStatefulClient that solves
    the CPU leak issue by running the entire context manager lifecycle in
    a single dedicated background task.

    Supports both streamable HTTP and SSE transports.
    """

    def __init__(
        self,
        name: Any,
        transport: Any,
        url: Any,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
        sse_read_timeout: float = 60 * 5,
        **client_kwargs: Any,
    ) -> None:
        """Initialize the HTTP MCP client.

        Args:
            name: Client identifier (unique across MCP servers)
            transport: The transport type ("streamable_http" or "sse")
            url: The URL to the MCP server
            headers: Additional headers to include in the HTTP request
            timeout: The timeout for the HTTP request in seconds
            sse_read_timeout: The timeout for reading SSE in seconds
            **client_kwargs: Additional keyword arguments for the client

        Raises:
            TypeError: If name, transport, or url is not a string
            ValueError: If transport is not "streamable_http" or "sse"
        """
        if not isinstance(name, str):
            raise TypeError(f"name must be str, got {type(name).__name__}")
        if not isinstance(transport, str):
            raise TypeError(
                f"transport must be str, got {type(transport).__name__}",
            )
        if transport not in ["streamable_http", "sse"]:
            raise ValueError(
                f"transport must be 'streamable_http' or 'sse', "
                f"got {transport!r}",
            )
        if not isinstance(url, str):
            raise TypeError(f"url must be str, got {type(url).__name__}")

        self.name = name
        self.is_stateful = True
        self.transport = transport
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.sse_read_timeout = sse_read_timeout
        self.read_timeout_seconds = sse_read_timeout
        self.client_kwargs = client_kwargs

        # Lifecycle management
        self._lifecycle_task: asyncio.Task | None = None
        self._reload_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._session_closed = asyncio.Event()
        self._rpc_tasks: set[asyncio.Task] = set()
        self._oauth_required = False

        # Exponential backoff & circuit breaker
        self._reconnect_delay: float = 1.0
        self._consecutive_failures: int = 0
        self._circuit_open: bool = False
        self._circuit_open_since: float = 0.0
        self._max_reconnect_delay: float = 60.0
        self._circuit_breaker_threshold: int = 5
        self._circuit_half_open_after: float = 300.0

        # Session state
        self.session: ClientSession | None = None
        self.is_connected = False

        # Tool cache
        self._cached_tools = None

    async def _setup_transport(
        self,
        stack: AsyncExitStack,
    ) -> tuple[Any, Any]:
        if self.transport == "streamable_http":
            timeout_seconds = (
                self.timeout.total_seconds()
                if isinstance(self.timeout, timedelta)
                else self.timeout
            )
            sse_read_timeout_seconds = (
                self.sse_read_timeout.total_seconds()
                if isinstance(self.sse_read_timeout, timedelta)
                else self.sse_read_timeout
            )
            http_client = httpx.AsyncClient(
                headers=self.headers or {},
                timeout=httpx.Timeout(
                    connect=timeout_seconds,
                    read=sse_read_timeout_seconds,
                    write=timeout_seconds,
                    pool=timeout_seconds,
                ),
                **self.client_kwargs,
            )
            await stack.enter_async_context(http_client)
            context = await stack.enter_async_context(
                streamable_http_client(url=self.url, http_client=http_client),
            )
        else:
            context = await stack.enter_async_context(
                sse_client(
                    url=self.url,
                    headers=self.headers,
                    timeout=self.timeout,
                    sse_read_timeout=self.sse_read_timeout,
                    **self.client_kwargs,
                ),
            )
        return context[0], context[1]

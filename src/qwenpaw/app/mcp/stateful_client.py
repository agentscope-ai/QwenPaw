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
import re
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Literal

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from agentscope.mcp import MCPToolFunction, StatefulClientBase

# OpenAI / Anthropic tool-call APIs reject any tools[].name that contains
# characters outside this set. MCP, by contrast, allows '.', '/', ':' etc.,
# so we have to sanitize before forwarding to the model and route back to the
# original name on dispatch. Keep the regex identical to OpenAI's published
# constraint to fail-fast against the strictest validator we know of.
_TOOL_NAME_ALLOWED = re.compile(r"^[a-zA-Z0-9_-]+$")
_TOOL_NAME_REPLACE = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize_tool_name(raw: str, taken: set[str]) -> str:
    """Map *raw* to a name matching ``^[a-zA-Z0-9_-]+$``, avoiding *taken*.

    Returns *raw* unchanged when it is already valid AND not already in use.
    Otherwise replaces every disallowed character with ``_`` and, if the
    result collides with anything in *taken* (e.g. a real upstream tool that
    happens to share the same sanitized form), appends ``_2``, ``_3``…
    until unique. The empty-string edge case is mapped to ``_``.
    """
    if _TOOL_NAME_ALLOWED.match(raw) and raw not in taken:
        return raw
    base = _TOOL_NAME_REPLACE.sub("_", raw) or "_"
    candidate = base
    suffix = 2
    while candidate in taken:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


class _SessionAliasProxy:
    """Wrap a ``ClientSession`` to translate sanitized tool names back to
    the real MCP names on ``call_tool``.

    The toolkit dispatch path (``MCPToolFunction.__call__``) calls
    ``self.session.call_tool(self.name, ...)`` directly on the underlying
    ``mcp.ClientSession``, bypassing any ``call_tool`` override on this
    client. Wrapping the session at the point we hand it to
    ``MCPToolFunction`` is the only place the translation can happen
    without forking ``MCPToolFunction`` itself. All other session
    attributes are forwarded as-is via ``__getattr__``.
    """

    def __init__(
        self,
        session: ClientSession,
        alias_to_real: dict[str, str],
    ) -> None:
        # Snapshot the mapping by reference; the client rebinds
        # ``_name_alias_to_real`` to a fresh dict on reconnect, so this
        # proxy keeps routing in-flight functions through the mapping
        # that was current when the function was constructed.
        self._session = session
        self._alias_to_real = alias_to_real

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    async def call_tool(
        self,
        name: str,
        arguments: dict | None = None,
        **kwargs: Any,
    ) -> Any:
        real_name = self._alias_to_real.get(name, name)
        # Forward ``arguments`` as keyword to match how
        # ``MCPToolFunction.__call__`` invokes this method (and how the
        # underlying ``ClientSession.call_tool`` is normally called).
        return await self._session.call_tool(
            real_name,
            arguments=arguments,
            **kwargs,
        )


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


def _is_transport_error(exc: BaseException) -> bool:
    """Return ``True`` if *exc* indicates a broken or closed transport.

    Transport errors mean the underlying stream is dead; the client should
    reconnect rather than treat the failure as permanent.  See
    ``_TRANSPORT_ERRORS`` for the full list of recognised exception types.
    """
    return isinstance(exc, _TRANSPORT_ERRORS)


def _is_401_error(exc: BaseException) -> bool:
    """Return True if exc (or any sub-exception) is HTTP 401."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 401
    # ExceptionGroup wraps one or more sub-exceptions (Python 3.11+)
    sub_excs = getattr(exc, "exceptions", None)
    if sub_excs:
        return any(_is_401_error(e) for e in sub_excs)
    return False


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
    _oauth_required: bool
    _cached_tools: Any
    _name_alias_to_real: dict[str, str]
    _stop_event: asyncio.Event
    _reload_event: asyncio.Event
    _ready_event: asyncio.Event
    _lifecycle_task: asyncio.Task | None

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
        """Run MCP client lifecycle in a dedicated task.

        This ensures ``__aenter__`` and ``__aexit__`` are called in the
        same asyncio task, avoiding the cross-task cancel-scope error.
        Transport setup is delegated to ``_setup_transport``.
        """
        while not self._stop_event.is_set():
            try:
                logger.debug(f"Connecting MCP client: {self.name}")

                async with AsyncExitStack() as stack:
                    read_stream, write_stream = await self._setup_transport(
                        stack,
                    )

                    self.session = ClientSession(read_stream, write_stream)
                    await stack.enter_async_context(self.session)
                    await self.session.initialize()

                    self.is_connected = True
                    self._ready_event.set()
                    logger.info(f"MCP client connected: {self.name}")

                    # Wait for a reload or stop signal (0.1 s poll).
                    while (
                        not self._reload_event.is_set()
                        and not self._stop_event.is_set()
                    ):
                        await asyncio.sleep(0.1)

                    # Clear state before the context manager exits and
                    # tears down the transport / subprocess.
                    self.session = None
                    self.is_connected = False
                    self._cached_tools = None
                    self._name_alias_to_real = {}

                    if self._reload_event.is_set():
                        logger.info(f"Reloading MCP client: {self.name}")
                        self._reload_event.clear()
                        self._ready_event.clear()
                    else:
                        logger.info(f"Stopping MCP client: {self.name}")

                # AsyncExitStack exits here in THIS task — no cross-task issue.

            except Exception as e:
                # 401 means the server requires OAuth; fail fast and signal
                # connect() so it can raise instead of returning silently.
                if _is_401_error(e):
                    logger.info(
                        f"MCP client '{self.name}': server requires OAuth "
                        "(HTTP 401). Authorize via the UI to connect.",
                    )
                    self._oauth_required = True
                    self._stop_event.set()
                    self._ready_event.set()
                    return
                logger.error(
                    f"Error in MCP client lifecycle for {self.name}: {e}",
                    exc_info=True,
                )
                self.session = None
                self.is_connected = False
                self._cached_tools = None
                self._name_alias_to_real = {}
                self._ready_event.clear()
                await asyncio.sleep(1)

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
        # set from a previous connect/close cycle because the stop path
        # in _run_lifecycle does not clear it).
        self._stop_event.clear()
        self._oauth_required = False
        self._ready_event.clear()
        self._lifecycle_task = asyncio.create_task(self._run_lifecycle())

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout waiting for MCP client '{self.name}' to connect",
            )
            self._stop_event.set()
            if self._lifecycle_task:
                await self._lifecycle_task
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
            RuntimeError: If not connected.
            asyncio.TimeoutError: If the new connection is not
                established within *timeout* seconds.
        """
        if not self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is not connected. "
                f"Call connect() first.",
            )

        logger.info(f"Triggering reload for MCP client: {self.name}")
        self._reload_event.set()
        # Clear _ready_event *before* waiting.  When connected,
        # _ready_event is already set; without this clear, the wait
        # below would return immediately before the reload has started.
        self._ready_event.clear()

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            logger.info(f"Reload completed for MCP client: {self.name}")
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout waiting for MCP client '{self.name}' to reload",
            )
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_tools(self):
        """Return all tools available from the MCP server.

        MCP allows tool names with characters (``.``, ``/``, ``:``…) that
        OpenAI- and Anthropic-style tool-call APIs reject. To stay compatible
        without losing the ability to dispatch back to the real tool, this
        method rewrites each non-conformant ``tool.name`` to a sanitized
        alias and stores the alias→real mapping on the client. Subsequent
        :meth:`call_tool` lookups consult that mapping. Tools whose names are
        already valid pass through untouched, with no mapping entry.

        Returns:
            List of MCP tools whose names are guaranteed to match
            ``^[a-zA-Z0-9_-]+$``.

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        try:
            res = await self.session.list_tools()
        except Exception as exc:
            self._handle_transport_error(exc)
            raise

        rewritten: list = []
        alias_to_real: dict[str, str] = {}
        # Reserve the set of safe names already taken so collisions
        # (e.g. upstream exposes both ``a.b`` and ``a_b``) get a suffix.
        taken: set[str] = {
            t.name for t in res.tools if _TOOL_NAME_ALLOWED.match(t.name)
        }
        for tool in res.tools:
            if _TOOL_NAME_ALLOWED.match(tool.name):
                rewritten.append(tool)
                continue
            safe = _sanitize_tool_name(tool.name, taken)
            taken.add(safe)
            alias_to_real[safe] = tool.name
            rewritten.append(tool.model_copy(update={"name": safe}))
            logger.info(
                "MCP client '%s': renamed tool '%s' -> '%s' for "
                "model-side compatibility.",
                self.name,
                tool.name,
                safe,
            )

        self._cached_tools = rewritten
        self._name_alias_to_real = alias_to_real
        return rewritten

    async def call_tool(self, name: str, arguments: dict | None = None):
        """Call a tool on the MCP server with its real MCP name.

        Note: this is a pure pass-through and does NOT translate sanitized
        aliases. Sanitization-aware dispatch lives on
        :meth:`get_callable_function` (which is what agentscope's toolkit
        actually invokes). Callers reaching this method directly should
        pass the real MCP tool name.

        Args:
            name: The real MCP tool name (as returned by the server).
            arguments: Tool arguments (optional)

        Returns:
            Tool call result

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        try:
            return await self.session.call_tool(name, arguments or {})
        except Exception as exc:
            self._handle_transport_error(exc)
            raise

    async def get_callable_function(
        self,
        func_name: str,
        wrap_tool_result: bool = True,
        execution_timeout: float | None = None,
    ) -> MCPToolFunction:
        """Build the ``MCPToolFunction`` agentscope dispatches through, with
        a session that translates sanitized names back to MCP-real names.

        The agentscope toolkit reads ``mcp_tool.name`` from our
        :meth:`list_tools` (already sanitized) and passes it here as
        ``func_name``. Without intervention, ``MCPToolFunction.__call__``
        would dispatch the sanitized name to a server that only knows the
        real name, returning "Unknown tool".

        We construct ``MCPToolFunction`` ourselves rather than delegating
        to the inherited implementation so the proxy is wired in at
        construction time — the returned function then exposes the
        sanitized ``name`` (correct for the model) and dispatches the real
        MCP name (correct for the server) without any post-hoc mutation.
        """
        self._validate_connection()

        if self._cached_tools is None:
            await self.list_tools()

        target_tool = next(
            (t for t in self._cached_tools if t.name == func_name),
            None,
        )
        if target_tool is None:
            raise ValueError(
                f"Tool '{func_name}' not found in MCP server '{self.name}'",
            )

        session: Any = self.session
        if self._name_alias_to_real:
            session = _SessionAliasProxy(session, self._name_alias_to_real)

        return MCPToolFunction(
            mcp_name=self.name,
            tool=target_tool,
            wrap_tool_result=wrap_tool_result,
            session=session,
            timeout=execution_timeout,
        )

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

        try:
            # Signal stop and wait for the lifecycle task to finish.  This
            # must happen even when is_connected is False (reconnect loop).
            self._stop_event.set()
            if self._lifecycle_task:
                await self._lifecycle_task
        except Exception as e:
            if not ignore_errors:
                raise
            logger.warning(
                f"Error closing MCP client '{self.name}': {e}",
            )
        finally:
            # Clear the reference unconditionally — including when the current
            # coroutine is cancelled (CancelledError is BaseException, not
            # Exception, so it bypasses the except block above).  _stop_event
            # is already set at this point, so the task will exit on its next
            # iteration even if we don't hold the reference.
            self._lifecycle_task = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_transport_error(self, exc: BaseException) -> None:
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

        By proactively setting ``is_connected=False`` and firing
        ``_reload_event``, we ensure the lifecycle loop's inner 0.1 s poll
        detects the dead stream and tears down the old context before opening
        a fresh connection.

        Note: ``self.session`` is intentionally *not* cleared here.
        ``_validate_connection`` checks ``is_connected`` first, so the stale
        ``session`` reference is never reached before the lifecycle task
        replaces it.  Clearing it here would require a lock (the lifecycle
        task also writes ``session``), adding unnecessary complexity.
        """
        if not _is_transport_error(exc):
            return
        logger.warning(
            "Transport error on MCP client '%s' (%s: %s); "
            "marking as disconnected and scheduling reconnect.",
            self.name,
            type(exc).__name__,
            exc,
        )
        self.is_connected = False
        self._cached_tools = None
        self._name_alias_to_real = {}
        # session is left as-is; see docstring above.
        if not self._stop_event.is_set():
            self._reload_event.set()

    def _validate_connection(self) -> None:
        """Raise ``RuntimeError`` if the session is not ready.

        Raises:
            RuntimeError: If not connected or session not initialized
        """
        if not self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is not connected. "
                f"Call connect() first.",
            )

        if not self.session:
            raise RuntimeError(
                f"MCP client '{self.name}' session is not initialized. "
                f"Call connect() first.",
            )


class StdIOStatefulClient(_MCPClientMixin, StatefulClientBase):
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
        self._oauth_required = False

        # Session state
        self.session: ClientSession | None = None
        self.is_connected = False

        # Tool cache
        self._cached_tools = None
        self._name_alias_to_real: dict[str, str] = {}

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


class HttpStatefulClient(_MCPClientMixin, StatefulClientBase):
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
        self._oauth_required = False

        # Session state
        self.session: ClientSession | None = None
        self.is_connected = False

        # Tool cache
        self._cached_tools = None
        self._name_alias_to_real: dict[str, str] = {}

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

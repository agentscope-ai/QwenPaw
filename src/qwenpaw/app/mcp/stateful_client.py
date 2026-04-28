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
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Literal

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from agentscope.mcp import StatefulClientBase

logger = logging.getLogger(__name__)


class StdIOStatefulClient(StatefulClientBase):
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
        **kwargs,
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

        # Lifecycle management
        self._lifecycle_task: asyncio.Task | None = None
        self._reload_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()

        # Session state
        self.session: ClientSession | None = None
        self.is_connected = False

        # Tool cache
        self._cached_tools = None

        self.timeout = kwargs.get("timeout")

    async def _run_lifecycle(self) -> None:
        """Run MCP client lifecycle in a dedicated task.

        This ensures __aenter__ and __aexit__ are called in the same task,
        avoiding the cross-task cancel scope error.
        """
        from mcp.client.stdio import stdio_client

        while not self._stop_event.is_set():
            try:
                logger.debug(f"Connecting MCP client: {self.name}")

                # Enter context manager in THIS task
                async with AsyncExitStack() as stack:
                    context = await stack.enter_async_context(
                        stdio_client(self.server_params),
                    )
                    read_stream, write_stream = context[0], context[1]

                    # Initialize session
                    self.session = ClientSession(read_stream, write_stream)
                    await stack.enter_async_context(self.session)
                    await self.session.initialize()

                    # Mark as connected and signal ready
                    self.is_connected = True
                    self._ready_event.set()
                    logger.info(f"MCP client connected: {self.name}")

                    # Wait for reload or stop signal
                    while (
                        not self._reload_event.is_set()
                        and not self._stop_event.is_set()
                    ):
                        await asyncio.sleep(0.1)

                    # Clear state before exiting context
                    self.session = None
                    self.is_connected = False
                    self._cached_tools = None

                    if self._reload_event.is_set():
                        logger.info(f"Reloading MCP client: {self.name}")
                        self._reload_event.clear()
                        self._ready_event.clear()
                        # Context manager will exit here, then loop restarts
                    else:
                        logger.info(f"Stopping MCP client: {self.name}")
                        # Context manager will exit here, then loop exits

                # Context manager exits cleanly in THIS task

            except Exception as e:
                logger.error(
                    f"Error in MCP client lifecycle for {self.name}: {e}",
                    exc_info=True,
                )
                self.session = None
                self.is_connected = False
                self._cached_tools = None
                self._ready_event.clear()
                await asyncio.sleep(1)

        logger.info(f"MCP client lifecycle task exited: {self.name}")

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect to MCP server.

        Args:
            timeout: Connection timeout in seconds (default 30s)

        Raises:
            RuntimeError: If already connected
            asyncio.TimeoutError: If connection times out
        """
        if self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is already connected. "
                f"Call close() before connecting again.",
            )

        # Start lifecycle task
        self._stop_event.clear()
        self._lifecycle_task = asyncio.create_task(self._run_lifecycle())

        # Wait for initial connection
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout waiting for MCP client '{self.name}' to connect",
            )
            # Clean up failed task
            self._stop_event.set()
            if self._lifecycle_task:
                await self._lifecycle_task
            raise

    async def close(self, ignore_errors: bool = True) -> None:
        """Close MCP client and clean up resources.

        Args:
            ignore_errors: Whether to ignore errors during cleanup

        Raises:
            RuntimeError: If not connected (unless ignore_errors=True)
        """
        if not self.is_connected:
            if not ignore_errors:
                raise RuntimeError(
                    f"MCP client '{self.name}' is not connected. "
                    f"Call connect() before closing.",
                )
            return

        try:
            # Signal stop and wait for lifecycle task to finish
            self._stop_event.set()
            if self._lifecycle_task:
                await self._lifecycle_task
                self._lifecycle_task = None
        except Exception as e:
            if not ignore_errors:
                raise
            logger.warning(
                f"Error closing MCP client '{self.name}': {e}",
            )

    async def reload(self, timeout: float = 30.0) -> None:
        """Reload the MCP client (reconnect).

        Args:
            timeout: Connection timeout in seconds (default 30s)

        Raises:
            RuntimeError: If not connected
            asyncio.TimeoutError: If reload times out
        """
        if not self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is not connected. "
                f"Call connect() first.",
            )

        logger.info(f"Triggering reload for MCP client: {self.name}")
        self._reload_event.set()

        # Wait for new connection
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            logger.info(f"Reload completed for MCP client: {self.name}")
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout waiting for MCP client '{self.name}' to reload",
            )
            raise

    async def list_tools(self):
        """Get all available tools from the server.

        Returns:
            List of available MCP tools

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        res = await self.session.list_tools()

        # Cache the tools for later use
        self._cached_tools = res.tools
        return res.tools

    async def call_tool(self, name: str, arguments: dict | None = None):
        """Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments (optional)

        Returns:
            Tool call result

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        return await self.session.call_tool(name, arguments or {})

    def _validate_connection(self) -> None:
        """Validate the connection to the MCP server.

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


class HttpStatefulClient(StatefulClientBase):
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
        self.client_kwargs = client_kwargs

        # Lifecycle management
        self._lifecycle_task: asyncio.Task | None = None
        self._reload_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()

        # Session state
        self.session: ClientSession | None = None
        self.is_connected = False

        # Tool cache
        self._cached_tools = None

    async def _run_lifecycle(self) -> None:
        """Run MCP client lifecycle in a dedicated task."""
        while not self._stop_event.is_set():
            try:
                logger.debug(f"Connecting MCP client: {self.name}")

                # Enter context manager in THIS task
                async with AsyncExitStack() as stack:
                    # Select client based on transport
                    if self.transport == "streamable_http":
                        # Create httpx.AsyncClient with headers and timeout
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

                        # Configure httpx client with MCP-recommended timeouts
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

                        # Add http_client to exit stack for proper cleanup
                        await stack.enter_async_context(http_client)

                        context = await stack.enter_async_context(
                            streamable_http_client(
                                url=self.url,
                                http_client=http_client,
                            ),
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

                    read_stream, write_stream = context[0], context[1]

                    # Initialize session
                    self.session = ClientSession(read_stream, write_stream)
                    await stack.enter_async_context(self.session)
                    await self.session.initialize()

                    # Mark as connected and signal ready
                    self.is_connected = True
                    self._ready_event.set()
                    logger.info(f"MCP client connected: {self.name}")

                    # Wait for reload or stop signal
                    while (
                        not self._reload_event.is_set()
                        and not self._stop_event.is_set()
                    ):
                        await asyncio.sleep(0.1)

                    # Clear state before exiting context
                    self.session = None
                    self.is_connected = False
                    self._cached_tools = None

                    if self._reload_event.is_set():
                        logger.info(f"Reloading MCP client: {self.name}")
                        self._reload_event.clear()
                        self._ready_event.clear()
                    else:
                        logger.info(f"Stopping MCP client: {self.name}")

                # Context manager exits cleanly in THIS task

            except Exception as e:
                logger.error(
                    f"Error in MCP client lifecycle for {self.name}: {e}",
                    exc_info=True,
                )
                self.session = None
                self.is_connected = False
                self._cached_tools = None
                self._ready_event.clear()
                await asyncio.sleep(1)

        logger.info(f"MCP client lifecycle task exited: {self.name}")

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect to MCP server.

        Args:
            timeout: Connection timeout in seconds

        Raises:
            RuntimeError: If already connected
            asyncio.TimeoutError: If connection times out
        """
        if self.is_connected:
            raise RuntimeError(
                f"MCP client '{self.name}' is already connected. "
                f"Call close() before connecting again.",
            )

        self._stop_event.clear()
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

    async def close(self, ignore_errors: bool = True) -> None:
        """Close MCP client and clean up resources.

        Args:
            ignore_errors: Whether to ignore errors during cleanup

        Raises:
            RuntimeError: If not connected (unless ignore_errors=True)
        """
        if not self.is_connected:
            if not ignore_errors:
                raise RuntimeError(
                    f"MCP client '{self.name}' is not connected. "
                    f"Call connect() before closing.",
                )
            return

        try:
            self._stop_event.set()
            if self._lifecycle_task:
                await self._lifecycle_task
                self._lifecycle_task = None
        except Exception as e:
            if not ignore_errors:
                raise
            logger.warning(
                f"Error closing MCP client '{self.name}': {e}",
            )

    async def list_tools(self):
        """Get all available tools from the server.

        Returns:
            List of available MCP tools

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        res = await self.session.list_tools()
        self._cached_tools = res.tools
        return res.tools

    async def call_tool(self, name: str, arguments: dict | None = None):
        """Call a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments (optional)

        Returns:
            Tool call result

        Raises:
            RuntimeError: If not connected
        """
        self._validate_connection()

        return await self.session.call_tool(name, arguments or {})

    def _validate_connection(self) -> None:
        """Validate the connection to the MCP server.

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

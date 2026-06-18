# -*- coding: utf-8 -*-
"""MCP client manager for hot-reloadable client lifecycle management.

This module provides centralized management of MCP clients with support
for runtime updates without restarting the application.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, TYPE_CHECKING

from .stateful_client import HttpStatefulClient, StdIOStatefulClient

if TYPE_CHECKING:
    from ...config.config import MCPClientConfig, MCPConfig

logger = logging.getLogger(__name__)


class MCPClientManager:
    """Manages MCP clients with hot-reload support.

    This manager handles the lifecycle of MCP clients, including:
    - Initial loading from config
    - Runtime replacement when config changes
    - Cleanup on shutdown

    Design pattern mirrors ChannelManager for consistency.
    """

    def __init__(self) -> None:
        """Initialize an empty MCP client manager."""
        self._clients: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._init_task: asyncio.Task[None] | None = None

    async def init_from_config(
        self,
        config: "MCPConfig",
        timeout: float = 60.0,
    ) -> None:
        """Initialize clients from configuration.

        Args:
            config: MCP configuration containing client definitions
            timeout: Connection timeout per client in seconds
        """
        logger.debug("Initializing MCP clients from config")
        for key, client_config in config.clients.items():
            if not client_config.enabled:
                logger.debug(f"MCP client '{key}' is disabled, skipping")
                continue

            try:
                await self._add_client(key, client_config, timeout=timeout)
                logger.debug(f"MCP client '{key}' initialized successfully")
            except BaseException as e:
                if isinstance(
                    e,
                    (KeyboardInterrupt, SystemExit, asyncio.CancelledError),
                ):
                    raise
                logger.warning(
                    f"Failed to initialize MCP client '{key}': {e}",
                    exc_info=True,
                )

    def init_from_config_background(
        self,
        config: "MCPConfig",
        timeout: float = 10.0,
    ) -> None:
        """Start MCP initialization without blocking workspace startup.

        The runner asks this manager for connected clients at query time, so
        clients that finish later become available without delaying ACP/TUI
        startup.  Repeated calls replace any still-running startup task.
        """
        if self._init_task is not None and not self._init_task.done():
            self._init_task.cancel()

        async def _run() -> None:
            try:
                await self.init_from_config(config, timeout=timeout)
            except Exception:
                logger.warning(
                    "Background MCP initialization failed",
                    exc_info=True,
                )

        self._init_task = asyncio.create_task(_run())
        self._init_task.add_done_callback(self._consume_init_task_result)

    @staticmethod
    def _consume_init_task_result(task: asyncio.Task[None]) -> None:
        """Consume background task result so cancellation is quiet."""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning(
                "Background MCP initialization task failed",
                exc_info=True,
            )

    async def get_clients(self) -> List[Any]:
        """Get list of all active MCP clients.

        This method is called by the runner on each query to get
        the latest set of clients.

        Returns:
            List of connected MCP client instances
        """
        async with self._lock:
            return [
                client
                for client in self._clients.values()
                if client is not None
            ]

    async def get_client(self, key: str) -> Any | None:
        """Get a specific active MCP client by key.

        Args:
            key: Client identifier (from config)

        Returns:
            Connected MCP client instance, or None if not found
        """
        async with self._lock:
            return self._clients.get(key)

    async def replace_client(
        self,
        key: str,
        client_config: "MCPClientConfig",
        timeout: float = 60.0,
    ) -> None:
        """Replace or add a client with new configuration.

        Flow: connect new (outside lock) → atomic swap (inside lock) →
        close old (outside lock).
        The lock is held only for the dict swap, not during the slow close().

        Args:
            key: Client identifier (from config)
            client_config: New client configuration
            timeout: Connection timeout in seconds (default 60s)
        """
        # 1. Create and connect new client outside lock (may be slow)
        logger.debug(f"Connecting new MCP client: {key}")
        new_client = self._build_client(client_config)

        try:
            # Add timeout to prevent indefinite blocking
            await asyncio.wait_for(new_client.connect(), timeout=timeout)
        except BaseException:
            await self._force_cleanup_client(new_client)
            raise

        # 2. Atomically swap inside lock (dict ops only — no async I/O here)
        async with self._lock:
            old_client = self._clients.get(key)
            self._clients[key] = new_client
            if old_client is None:
                logger.debug(f"Added new MCP client: {key}")

        # 3. Close old client outside lock — close() may await for up to
        #    a full reconnect sleep (≥1 s) and should not block get_clients()
        #    / get_client() / close_all().  Matches remove_client() pattern.
        if old_client is not None:
            logger.debug(f"Closing old MCP client: {key}")
            try:
                await old_client.close()
            except Exception as e:
                logger.warning(
                    f"Error closing old MCP client '{key}': {e}",
                )

    async def remove_client(self, key: str) -> None:
        """Remove and close a client.

        Args:
            key: Client identifier to remove
        """
        async with self._lock:
            old_client = self._clients.pop(key, None)

        if old_client is not None:
            logger.debug(f"Removing MCP client: {key}")
            try:
                await old_client.close()
            except Exception as e:
                logger.warning(f"Error closing MCP client '{key}': {e}")

    async def close_all(self) -> None:
        """Close all MCP clients concurrently.

        Called during application shutdown.  All clients are
        closed in parallel via ``asyncio.gather`` with a 30 s
        overall timeout so one hung client cannot block the rest.
        """
        if self._init_task is not None and not self._init_task.done():
            self._init_task.cancel()
            try:
                await self._init_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Error stopping MCP init task: {e}")
        self._init_task = None

        async with self._lock:
            clients_snapshot = list(self._clients.items())
            self._clients.clear()

        if not clients_snapshot:
            return

        logger.debug(
            f"Closing {len(clients_snapshot)} MCP client(s)",
        )

        async def _close_one(key: str, client) -> None:
            try:
                await client.close()
            except Exception as e:
                logger.warning(
                    f"Error closing MCP client '{key}': {e}",
                )

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(
                        _close_one(k, c)
                        for k, c in clients_snapshot
                        if c is not None
                    ),
                    return_exceptions=True,
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "MCP close_all timed out after 30s; "
                "some clients may not have shut down cleanly",
            )

        # Reap orphans only — PIDs that survived their client's
        # close().  Do NOT use include_active=True here because
        # another manager (e.g. new workspace after reload) may
        # have already registered fresh PIDs in the global table.
        from .stateful_client import kill_orphaned_mcp_children

        await kill_orphaned_mcp_children(include_active=False)

    async def _add_client(
        self,
        key: str,
        client_config: "MCPClientConfig",
        timeout: float = 60.0,
    ) -> None:
        """Add a new client (used during initial setup).

        Args:
            key: Client identifier
            client_config: Client configuration
            timeout: Connection timeout in seconds (default 60s)
        """
        client = self._build_client(client_config)

        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
        except BaseException:
            await self._force_cleanup_client(client)
            raise

        async with self._lock:
            self._clients[key] = client

    @staticmethod
    async def _force_cleanup_client(client: Any) -> None:
        """Force-close a client whose ``connect()`` was interrupted.

        Called when ``connect()`` raises (timeout or other error) so that
        any background lifecycle task and subprocess are torn down.

        For ``StdIOStatefulClient`` / ``HttpStatefulClient`` the
        ``connect()`` timeout path already calls ``_stop_event.set()``
        and ``await _lifecycle_task`` before re-raising, so by the time
        this helper runs the task is already done and ``close()`` returns
        early as a no-op.  The call is kept for correctness in edge-cases
        and for compatibility with other client implementations.
        """
        if client is None:
            return
        try:
            await client.close(ignore_errors=True)
        except Exception:
            logger.debug(
                "Error during force-cleanup of MCP client",
                exc_info=True,
            )

    @staticmethod
    def _inject_oauth_token(
        headers: dict,
        client_config: "MCPClientConfig",
    ) -> dict:
        """Inject OAuth Bearer token into headers if available and valid."""
        import time as _time

        oauth = client_config.oauth
        if not oauth or not oauth.access_token:
            return headers

        # Skip injection when token is expired. Token refresh is not yet
        # implemented, so injecting an expired token would only cause 401s.
        # expires_at=0 means no expiry was provided; treat as non-expiring.
        if oauth.expires_at > 0 and oauth.expires_at < _time.time():
            logger.warning(
                f"OAuth token for MCP client '{client_config.name}' "
                "has expired; skipping Authorization header injection. "
                "Please re-authorize via the UI.",
            )
            return headers

        result = dict(headers)
        result["Authorization"] = f"Bearer {oauth.access_token}"
        return result

    @staticmethod
    def _build_client(client_config: "MCPClientConfig") -> Any:
        """Build MCP client instance by configured transport."""
        rebuild_info = {
            "name": client_config.name,
            "transport": client_config.transport,
            "url": client_config.url,
            "headers": client_config.headers or None,
            "command": client_config.command,
            "args": list(client_config.args),
            "env": dict(client_config.env),
            "cwd": client_config.cwd or None,
        }

        whitelist = (
            set(client_config.tools)
            if client_config.tools is not None
            else None
        )

        if client_config.transport == "stdio":
            client = StdIOStatefulClient(
                name=client_config.name,
                command=client_config.command,
                args=client_config.args,
                env=client_config.env,
                cwd=client_config.cwd or None,
                tool_whitelist=whitelist,
            )
            setattr(client, "_qwenpaw_rebuild_info", rebuild_info)
            return client

        headers: dict = dict(client_config.headers or {})
        headers = {k: os.path.expandvars(v) for k, v in headers.items()}

        # Inject OAuth access token (overrides any manually set Authorization)
        headers = MCPClientManager._inject_oauth_token(
            headers,
            client_config,
        )

        client = HttpStatefulClient(
            name=client_config.name,
            transport=client_config.transport,
            url=client_config.url,
            headers=headers or None,
            tool_whitelist=whitelist,
        )
        setattr(client, "_qwenpaw_rebuild_info", rebuild_info)
        return client

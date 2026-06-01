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
        self._configs: Dict[str, "MCPClientConfig"] = {}
        self._lock = asyncio.Lock()

    async def init_from_config(self, config: "MCPConfig") -> None:
        """Initialize clients from configuration.

        Args:
            config: MCP configuration containing client definitions
        """
        logger.debug("Initializing MCP clients from config")
        for key, client_config in config.clients.items():
            if not client_config.enabled:
                logger.debug(f"MCP client '{key}' is disabled, skipping")
                continue

            try:
                await self._add_client(key, client_config)
                logger.debug(f"MCP client '{key}' initialized successfully")
            except BaseException as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(
                    f"Failed to initialize MCP client '{key}': {e}",
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

        Flow: acquire new from pool → atomic swap → release old to pool.

        Args:
            key: Client identifier (from config)
            client_config: New client configuration
            timeout: Connection timeout in seconds (default 60s)
        """
        from .pool import SharedMCPPool

        pool = SharedMCPPool.instance()

        # 1. Acquire new client from pool (may be slow)
        logger.debug(f"Acquiring new MCP client: {key}")
        new_client = await pool.acquire(
            client_config,
            builder=self._build_client,
            timeout=timeout,
        )

        # 2. Atomically swap inside lock
        async with self._lock:
            old_config = self._configs.get(key)
            self._clients[key] = new_client
            self._configs[key] = client_config
            if old_config is None:
                logger.debug(f"Added new MCP client: {key}")

        # 3. Release old client to pool outside lock
        if old_config is not None:
            logger.debug(f"Releasing old MCP client: {key}")
            try:
                await pool.release(old_config)
            except Exception as e:
                logger.warning(
                    f"Error releasing old MCP client '{key}': {e}",
                )

    async def remove_client(self, key: str) -> None:
        """Remove and release a client back to the shared pool.

        Args:
            key: Client identifier to remove
        """
        async with self._lock:
            self._clients.pop(key, None)
            config = self._configs.pop(key, None)

        if config is not None:
            from .pool import SharedMCPPool

            logger.debug(f"Removing MCP client: {key}")
            await SharedMCPPool.instance().release(config)

    async def close_all(self) -> None:
        """Release all MCP clients back to the shared pool.

        Called during application shutdown.  Clients are only actually
        closed when all agents have released them (refcount reaches 0).
        """
        from .pool import SharedMCPPool

        async with self._lock:
            configs_snapshot = list(self._configs.items())
            self._clients.clear()
            self._configs.clear()

        pool = SharedMCPPool.instance()
        logger.debug("Releasing all MCP clients to pool")
        for key, config in configs_snapshot:
            try:
                await pool.release(config)
            except Exception as e:
                logger.warning(f"Error releasing MCP client '{key}': {e}")

    async def _add_client(
        self,
        key: str,
        client_config: "MCPClientConfig",
        timeout: float = 60.0,
    ) -> None:
        """Add a new client (used during initial setup).

        Uses SharedMCPPool to reuse existing server processes when
        multiple agents share the same MCP configuration (#4842).

        Args:
            key: Client identifier
            client_config: Client configuration
            timeout: Connection timeout in seconds (default 60s)
        """
        from .pool import SharedMCPPool

        pool = SharedMCPPool.instance()
        client = await pool.acquire(
            client_config,
            builder=self._build_client,
            timeout=timeout,
        )

        async with self._lock:
            self._clients[key] = client
            self._configs[key] = client_config

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

        if client_config.transport == "stdio":
            client = StdIOStatefulClient(
                name=client_config.name,
                command=client_config.command,
                args=client_config.args,
                env=client_config.env,
                cwd=client_config.cwd or None,
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
        )
        setattr(client, "_qwenpaw_rebuild_info", rebuild_info)
        return client

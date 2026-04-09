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

    async def replace_client(
        self,
        key: str,
        client_config: "MCPClientConfig",
        timeout: float = 60.0,
    ) -> None:
        """Replace or add a client with new configuration.

        Flow: connect new (outside lock) → swap + close old (inside lock).
        This ensures minimal lock holding time.

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

        # 2. Swap and close old client inside lock
        async with self._lock:
            old_client = self._clients.get(key)
            self._clients[key] = new_client

            if old_client is not None:
                logger.debug(f"Closing old MCP client: {key}")
                try:
                    await old_client.close()
                except Exception as e:
                    logger.warning(
                        f"Error closing old MCP client '{key}': {e}",
                    )
            else:
                logger.debug(f"Added new MCP client: {key}")

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

    async def reconnect_disconnected(self, timeout: float = 30.0) -> None:
        """Best-effort reconnect MCP clients with broken transport state.

        A broken client may already advertise ``is_connected = False`` or may
        still claim it is connected while its underlying transport/session has
        already died. The latter happens with stdio MCP servers when the child
        process exits unexpectedly: the next protocol request fails, but the
        client flag does not flip automatically.

        Since ``stdio_client`` is a one-shot ``@asynccontextmanager`` that
        cannot be re-entered after close, we must **rebuild** a fresh client
        instance from the stored ``_copaw_rebuild_info`` metadata and swap
        it into the dict atomically.

        This method is designed to be called periodically (e.g. by the
        config watcher) so that broken connections recover automatically
        once the MCP server comes back.

        Args:
            timeout: Per-client probe/connect timeout in seconds (default 30s)
        """
        async with self._lock:
            clients_snapshot = list(self._clients.items())

        unhealthy_clients = []
        for key, client in clients_snapshot:
            if client is None:
                continue
            if not await self._is_client_healthy(
                key=key,
                client=client,
                timeout=timeout,
            ):
                unhealthy_clients.append((key, client))

        if not unhealthy_clients:
            return

        for key, old_client in unhealthy_clients:
            new_client = self._build_replacement_client(
                key=key,
                old_client=old_client,
            )
            if new_client is None:
                continue

            try:
                await asyncio.wait_for(
                    new_client.connect(),
                    timeout=timeout,
                )
            except Exception as e:
                logger.debug(
                    "Health check: failed to reconnect MCP client '%s': %s",
                    key,
                    e,
                )
                await self._close_client_quietly(new_client)
                continue

            await self._swap_reconnected_client(
                key=key,
                old_client=old_client,
                new_client=new_client,
            )

    @staticmethod
    async def _is_client_healthy(
        key: str,
        client: Any,
        timeout: float,
    ) -> bool:
        """Check whether a client is still usable by probing the live session.

        ``is_connected`` alone is not reliable for unexpected stdio crashes,
        so healthy clients are verified with a protocol-level ping.
        """
        if getattr(client, "is_connected", True) is False:
            return False

        session = getattr(client, "session", None)
        ping_fn = getattr(session, "send_ping", None)
        if not callable(ping_fn):
            return True

        try:
            await asyncio.wait_for(ping_fn(), timeout=timeout)
            return True
        except Exception as e:
            logger.debug(
                "Health check: MCP client '%s' probe failed: %s",
                key,
                e,
            )
            return False

    @staticmethod
    def _build_replacement_client(key: str, old_client: Any) -> Any | None:
        """Build a replacement client from the stale client's rebuild info."""
        rebuild_info = getattr(old_client, "_copaw_rebuild_info", None)
        if not isinstance(rebuild_info, dict):
            logger.debug(
                "Cannot reconnect MCP client '%s': no rebuild info",
                key,
            )
            return None

        return MCPClientManager._build_client_from_info(rebuild_info)

    async def _swap_reconnected_client(
        self,
        key: str,
        old_client: Any,
        new_client: Any,
    ) -> None:
        """Atomically replace a stale client and clean it up afterwards."""
        async with self._lock:
            if self._clients.get(key) is not old_client:
                await self._close_client_quietly(new_client)
                return
            self._clients[key] = new_client

        logger.info("MCP client '%s' reconnected via health check", key)
        try:
            await old_client.close()
        except Exception as e:
            logger.debug(
                "Health check: failed to close stale MCP client '%s': %s",
                key,
                e,
            )

    @staticmethod
    async def _close_client_quietly(client: Any) -> None:
        """Best-effort close helper for clients we no longer keep."""
        try:
            await client.close()
        except Exception:
            pass

    @staticmethod
    def _build_client_from_info(rebuild_info: dict) -> Any | None:
        """Build a fresh MCP client from stored rebuild metadata.

        Returns:
            A new (unconnected) client instance, or ``None`` on failure.
        """
        transport = rebuild_info.get("transport")
        name = rebuild_info.get("name")

        try:
            if transport == "stdio":
                client = StdIOStatefulClient(
                    name=name,
                    command=rebuild_info.get("command"),
                    args=rebuild_info.get("args", []),
                    env=rebuild_info.get("env", {}),
                    cwd=rebuild_info.get("cwd"),
                )
            else:
                client = HttpStatefulClient(
                    name=name,
                    transport=transport,
                    url=rebuild_info.get("url"),
                    headers=rebuild_info.get("headers"),
                )
            setattr(client, "_copaw_rebuild_info", rebuild_info)
            return client
        except Exception as e:
            logger.debug(
                "Failed to rebuild MCP client '%s' with transport '%s': %s",
                name,
                transport,
                e,
                exc_info=True,
            )
            return None

    async def close_all(self) -> None:
        """Close all MCP clients.

        Called during application shutdown.
        """
        async with self._lock:
            clients_snapshot = list(self._clients.items())
            self._clients.clear()

        logger.debug("Closing all MCP clients")
        for key, client in clients_snapshot:
            if client is not None:
                try:
                    await client.close()
                except Exception as e:
                    logger.warning(f"Error closing MCP client '{key}': {e}")

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

        ``StatefulClientBase.close()`` refuses to run when
        ``is_connected`` is still ``False`` (which is the case when
        ``connect()`` times out or raises).  We bypass that guard by
        closing the ``AsyncExitStack`` directly — this triggers the
        ``stdio_client`` finally-block that sends SIGTERM/SIGKILL to
        the child process.

        The ``ClientSession`` is registered on the same stack via
        ``enter_async_context``, so ``stack.aclose()`` exits it in
        LIFO order — no separate session teardown is needed.
        """
        if client is None:
            return

        stack = getattr(client, "stack", None)
        if stack is None:
            return

        try:
            await stack.aclose()
        except Exception:
            logger.debug(
                "Error during force-cleanup of MCP client",
                exc_info=True,
            )
        finally:
            for attr, default in (
                ("stack", None),
                ("session", None),
                ("is_connected", False),
            ):
                try:
                    setattr(client, attr, default)
                except Exception:
                    pass

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
            setattr(client, "_copaw_rebuild_info", rebuild_info)
            return client

        headers = client_config.headers
        if headers:
            headers = {k: os.path.expandvars(v) for k, v in headers.items()}

        client = HttpStatefulClient(
            name=client_config.name,
            transport=client_config.transport,
            url=client_config.url,
            headers=headers or None,
        )
        setattr(client, "_copaw_rebuild_info", rebuild_info)
        return client

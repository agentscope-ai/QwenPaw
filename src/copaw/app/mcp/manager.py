# -*- coding: utf-8 -*-
"""MCP client manager for hot-reloadable client lifecycle management.

This module provides centralized management of MCP clients with support
for runtime updates without restarting the application.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, TYPE_CHECKING

import httpx
from agentscope.mcp import HttpStatefulClient, StdIOStatefulClient

if TYPE_CHECKING:
    from ...config.config import MCPClientConfig, MCPConfig

logger = logging.getLogger(__name__)


class MCPAuthRequiredError(Exception):
    """Raised when MCP server returns 401 Unauthorized."""

    def __init__(
        self,
        client_key: str,
        message: str = "OAuth authorization required",
    ):
        self.client_key = client_key
        super().__init__(message)


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

    async def init_from_config(
        self,
        config: "MCPConfig",
        save_config_fn=None,
    ) -> None:
        """Initialize clients from configuration.

        Args:
            config: MCP configuration containing client definitions
            save_config_fn: Optional callback to save config
                when requires_auth is set
        """
        logger.debug("Initializing MCP clients from config")
        auth_required_clients = []

        for key, client_config in config.clients.items():
            if not client_config.enabled:
                logger.debug(f"MCP client '{key}' is disabled, skipping")
                continue

            try:
                await self._add_client(key, client_config)
                logger.debug(f"MCP client '{key}' initialized successfully")
                # Clear requires_auth flag on successful connection
                if client_config.requires_auth:
                    client_config.requires_auth = False
                    auth_required_clients.append(key)
            except MCPAuthRequiredError:
                # Mark client as requiring OAuth
                client_config.requires_auth = True
                auth_required_clients.append(key)
                logger.info(
                    f"MCP client '{key}' marked as requiring "
                    "OAuth authorization",
                )
            except BaseException as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(
                    f"Failed to initialize MCP client '{key}': {e}",
                    exc_info=True,
                )

        # Save config if any auth states changed
        if auth_required_clients and save_config_fn:
            try:
                save_config_fn()
                logger.debug(
                    "Saved config with auth state changes for: "
                    f"{auth_required_clients}",
                )
            except Exception as e:
                logger.warning(f"Failed to save config: {e}")

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
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout connecting MCP client '{key}' after {timeout}s",
            )
            try:
                await new_client.close()
            except Exception:
                pass
            raise
        except Exception as e:
            logger.warning(f"Failed to connect MCP client '{key}': {e}")
            try:
                await new_client.close()
            except Exception:
                pass
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

    async def _check_auth_required(
        self,
        key: str,
        client_config: "MCPClientConfig",
    ) -> bool:
        """Pre-check if MCP server requires OAuth by sending a probe request.

        Returns:
            True if server returns 401 (auth required), False otherwise
        """
        if client_config.transport == "stdio":
            return False

        if not client_config.url:
            return False

        # Skip check if we already have a valid token
        if (
            client_config.oauth_token
            and client_config.oauth_token.access_token
        ):
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                # Send MCP initialize request to check auth
                response = await http_client.post(
                    client_config.url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "params": {"capabilities": {}},
                        "id": 1,
                    },
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 401:
                    logger.info(
                        f"MCP client '{key}' requires "
                        "OAuth authorization (401)",
                    )
                    return True
        except Exception as e:
            # Log but don't fail - let the actual connection handle errors
            logger.debug(f"Auth pre-check failed for '{key}': {e}")

        return False

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

        Raises:
            MCPAuthRequiredError: If server returns 401 Unauthorized
        """
        # Pre-check for OAuth requirement before attempting MCP connection
        if await self._check_auth_required(key, client_config):
            raise MCPAuthRequiredError(key)

        client = self._build_client(client_config)

        try:
            # Add timeout to prevent indefinite blocking
            await asyncio.wait_for(client.connect(), timeout=timeout)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.info(
                    f"MCP client '{key}' requires OAuth authorization (401)",
                )
                try:
                    await client.close()
                except Exception:
                    pass
                raise MCPAuthRequiredError(key) from e
            raise
        except Exception as e:
            # Check if the error message indicates 401
            error_str = str(e).lower()
            if "401" in error_str or "unauthorized" in error_str:
                logger.info(
                    f"MCP client '{key}' requires OAuth authorization",
                )
                try:
                    await client.close()
                except Exception:
                    pass
                raise MCPAuthRequiredError(key) from e
            raise

        async with self._lock:
            self._clients[key] = client

    @staticmethod
    def _build_client(client_config: "MCPClientConfig") -> Any:
        """Build MCP client instance by configured transport.

        If OAuth token is present, it will be injected as Authorization header.
        """
        # Start with configured headers
        headers = dict(client_config.headers) if client_config.headers else {}

        # Inject OAuth token if available
        if (
            client_config.oauth_token
            and client_config.oauth_token.access_token
        ):
            token_type = client_config.oauth_token.token_type or "Bearer"
            headers[
                "Authorization"
            ] = f"{token_type} {client_config.oauth_token.access_token}"
            logger.debug(
                f"Injected OAuth token for client '{client_config.name}'",
            )

        rebuild_info = {
            "name": client_config.name,
            "transport": client_config.transport,
            "url": client_config.url,
            "headers": headers or None,
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

        client = HttpStatefulClient(
            name=client_config.name,
            transport=client_config.transport,
            url=client_config.url,
            headers=headers or None,
        )
        setattr(client, "_copaw_rebuild_info", rebuild_info)
        return client

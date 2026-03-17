# -*- coding: utf-8 -*-
"""MCP client manager for hot-reloadable client lifecycle management.

This module provides centralized management of MCP clients with support
for runtime updates without restarting the application.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, TYPE_CHECKING

from agentscope.mcp import HttpStatefulClient, StdIOStatefulClient

if TYPE_CHECKING:
    from ...config.config import MCPClientConfig, MCPConfig

logger = logging.getLogger(__name__)

# Pattern for ${VAR_NAME} placeholders in config values.
_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


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

        # Add timeout to prevent indefinite blocking
        await asyncio.wait_for(client.connect(), timeout=timeout)

        async with self._lock:
            self._clients[key] = client

    @staticmethod
    def _expand_env_vars(value: str) -> str:
        """Expand ``${VAR_NAME}`` placeholders in *value* from environment.

        Unresolved placeholders (env var not set) are left as-is and a
        warning is logged so the user can diagnose missing variables.
        """

        def _replacer(match: re.Match) -> str:
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is None:
                logger.warning(
                    "Environment variable '%s' used in MCP config is not set; "
                    "placeholder will be sent as-is. "
                    "Set it via `copaw env set %s <value>` or system env.",
                    var_name,
                    var_name,
                )
                return match.group(0)
            return env_value

        return _ENV_VAR_RE.sub(_replacer, value)

    @classmethod
    def _expand_config_strings(
        cls,
        client_config: "MCPClientConfig",
    ) -> Dict[str, Any]:
        """Return a dict of resolved config values with env vars expanded.

        Only string-typed fields that may contain ``${VAR}`` are expanded.
        The original *client_config* is **not** mutated.
        """
        expand = cls._expand_env_vars
        return {
            "name": client_config.name,
            "transport": client_config.transport,
            "url": expand(client_config.url) if client_config.url else "",
            "headers": (
                {k: expand(v) for k, v in client_config.headers.items()}
                if client_config.headers
                else None
            ),
            "command": (
                expand(client_config.command) if client_config.command else ""
            ),
            "args": [expand(a) for a in client_config.args],
            "env": (
                {k: expand(v) for k, v in client_config.env.items()}
                if client_config.env
                else {}
            ),
            "cwd": (expand(client_config.cwd) if client_config.cwd else None),
        }

    @classmethod
    def _build_client(cls, client_config: "MCPClientConfig") -> Any:
        """Build MCP client instance by configured transport."""
        resolved = cls._expand_config_strings(client_config)

        # rebuild_info stores the *raw* (unexpanded) template so that the
        # config watcher can still detect changes to the template itself.
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
                name=resolved["name"],
                command=resolved["command"],
                args=resolved["args"],
                env=resolved["env"],
                cwd=resolved["cwd"],
            )
            setattr(client, "_copaw_rebuild_info", rebuild_info)
            return client

        client = HttpStatefulClient(
            name=resolved["name"],
            transport=resolved["transport"],
            url=resolved["url"],
            headers=resolved["headers"],
        )
        setattr(client, "_copaw_rebuild_info", rebuild_info)
        return client

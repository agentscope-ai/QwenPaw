# -*- coding: utf-8 -*-
"""MCP client manager for hot-reloadable client lifecycle management.

This module provides centralized management of MCP clients with support
for runtime updates without restarting the application.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    TYPE_CHECKING,
)

from .stateful_client import HttpStatefulClient, StdIOStatefulClient
from . import oauth as mcp_oauth

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

    def __init__(self, agent_id: Optional[str] = None) -> None:
        """Initialize an empty MCP client manager.

        Args:
            agent_id: Owning agent id. Used to construct OAuth auth
                providers that resolve tokens from the agent's config
                at connect time.
        """
        self._clients: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._agent_id = agent_id
        self._refresh_locks: Dict[str, asyncio.Lock] = {}

    def set_agent_id(self, agent_id: str) -> None:
        """Bind this manager to an agent (called when reused on reload)."""
        self._agent_id = agent_id

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
        new_client = self._build_client(client_config, key)

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
        client = self._build_client(client_config, key)

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
        """Inject OAuth Bearer token into headers if available."""
        auth = getattr(client_config, "auth", None)
        if (
            auth is None
            or getattr(auth, "type", None) != "oauth2"
            or not auth.access_token
        ):
            return headers

        now = int(time.time())
        if auth.token_expires_at > 0 and auth.token_expires_at < now:
            logger.warning(
                f"OAuth token for MCP client '{client_config.name}' "
                "has expired; skipping Authorization header injection. "
                "Please re-authorize via the UI.",
            )
            return headers

        result = dict(headers)
        result["Authorization"] = f"Bearer {auth.access_token}"
        return result

    def _build_client(
        self,
        client_config: "MCPClientConfig",
        client_key: str,
    ) -> Any:
        """Build MCP client instance by configured transport.

        For HTTP/SSE clients with OAuth configured, wires up an
        ``auth_provider`` closure that reads (and lazily refreshes) tokens
        from the owning agent's persisted config on every (re)connect.
        """
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

        auth_provider = None
        if client_config.auth is not None and self._agent_id:
            auth_provider = self._make_auth_provider(client_key)

        client = HttpStatefulClient(
            name=client_config.name,
            transport=client_config.transport,
            url=client_config.url,
            headers=headers or None,
            auth_provider=auth_provider,
        )
        setattr(client, "_qwenpaw_rebuild_info", rebuild_info)
        return client

    def _make_auth_provider(
        self,
        client_key: str,
    ) -> Callable[[], Awaitable[Dict[str, str]]]:
        """Build an auth_provider closure for a given MCP client key.

        The closure re-reads the agent config on every call so that newly
        persisted tokens take effect on reconnect. If the access token is
        near expiry it transparently refreshes it (and writes the result
        back to the agent config) before returning.
        """
        agent_id = self._agent_id
        if agent_id is None:

            async def _noop() -> Dict[str, str]:
                return {}

            return _noop

        async def _provider() -> Dict[str, str]:
            return await self._resolve_auth_headers(agent_id, client_key)

        return _provider

    async def _resolve_auth_headers(
        self,
        agent_id: str,
        client_key: str,
    ) -> Dict[str, str]:
        """Resolve current Authorization headers for an OAuth-protected
        MCP client, refreshing the access token if it is about to expire.
        """
        from ...config.config import load_agent_config, save_agent_config

        try:
            cfg = load_agent_config(agent_id)
        except Exception as e:
            logger.warning(
                "auth_provider: failed to load agent config for %s: %s",
                agent_id,
                e,
            )
            return {}

        mcp_cfg = cfg.mcp
        if mcp_cfg is None or client_key not in (mcp_cfg.clients or {}):
            return {}

        client_cfg = mcp_cfg.clients[client_key]
        auth = client_cfg.auth
        if auth is None or auth.type != "oauth2":
            return {}

        # Refresh if access_token missing or about to expire (60 s margin)
        now = int(time.time())
        needs_refresh = not auth.access_token or (
            auth.token_expires_at and auth.token_expires_at - now < 60
        )

        if needs_refresh and auth.refresh_token:
            lock = self._refresh_locks.setdefault(client_key, asyncio.Lock())
            async with lock:
                # Re-read after acquiring lock to avoid double-refresh
                cfg = load_agent_config(agent_id)
                clients = cfg.mcp.clients  # type: ignore[union-attr]
                client_cfg = clients[client_key]
                auth = client_cfg.auth  # type: ignore[assignment]
                now = int(time.time())
                still_needs = not auth.access_token or (
                    auth.token_expires_at and auth.token_expires_at - now < 60
                )
                if still_needs:
                    try:
                        tokens = await mcp_oauth.refresh_access_token(
                            token_endpoint=auth.token_endpoint,
                            refresh_token=auth.refresh_token,
                            client_id=auth.client_id,
                            client_secret=auth.client_secret,
                        )
                    except mcp_oauth.OAuthError as e:
                        logger.warning(
                            "Token refresh failed for MCP '%s': %s",
                            client_key,
                            e,
                        )
                        # Leave tokens untouched; let the next connect
                        # surface the 401 to the user via auth_state UI.
                        return (
                            {"Authorization": f"Bearer {auth.access_token}"}
                            if auth.access_token
                            else {}
                        )

                    auth.access_token = tokens.get("access_token", "")
                    if "refresh_token" in tokens:
                        # AS rotates refresh tokens — persist atomically
                        auth.refresh_token = tokens["refresh_token"]
                    auth.token_expires_at = mcp_oauth.compute_token_expires_at(
                        tokens.get("expires_in"),
                    )
                    if tokens.get("scope"):
                        auth.scope = tokens["scope"]
                    client_cfg.auth = auth
                    mcp_clients = cfg.mcp.clients  # type: ignore[union-attr]
                    mcp_clients[client_key] = client_cfg
                    try:
                        save_agent_config(agent_id, cfg)
                    except Exception as e:
                        logger.warning(
                            "Failed to persist refreshed tokens for '%s': %s",
                            client_key,
                            e,
                        )

        if auth.access_token:
            return {"Authorization": f"Bearer {auth.access_token}"}
        return {}

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

from agentscope.mcp import HttpStatefulClient, StdIOStatefulClient

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
        # Keys that failed to connect at startup or disconnected at runtime
        self._failed_keys: set = set()
        # Last runtime error details per client key for UI diagnostics.
        self._last_errors: Dict[str, Dict[str, Any]] = {}

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
                self._failed_keys.discard(key)
                self._clear_last_error(key)
            except BaseException as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                self._failed_keys.add(key)
                self._set_last_error(key, e)
                logger.warning(
                    f"MCP client '{key}' unavailable at startup"
                    f" ({self.describe_exception(e)})."
                    " Will be retried automatically.",
                )

    def active_keys(self) -> set:
        """Return the set of currently connected client keys.

        Uses ``is_connected`` from the underlying client object so that
        runtime disconnections are reflected without a heartbeat round-trip.
        """
        return {
            key
            for key, client in self._clients.items()
            if getattr(client, "is_connected", True)
        }

    def failed_keys(self) -> set:
        """Return keys that need reconnection.

        Combines startup failures (``_failed_keys``) with clients that
        connected initially but have since dropped (``is_connected=False``).
        """
        disconnected = {
            key
            for key, client in self._clients.items()
            if not getattr(client, "is_connected", True)
        }
        return self._failed_keys | disconnected

    def get_last_error(self, key: str) -> Dict[str, Any] | None:
        """Return last known runtime error details for a client key."""
        return self._last_errors.get(key)

    def is_active(self, key: str) -> bool:
        """Return whether a given client is currently connected."""
        client = self._clients.get(key)
        if client is None:
            return False
        return bool(getattr(client, "is_connected", True))

    async def refresh_client_status(
        self,
        key: str,
        client_config: "MCPClientConfig",
        timeout: float = 15.0,
    ) -> bool:
        """Actively probe and reconnect a client if needed.

        Returns:
            True if the client is connected after refresh, False otherwise.
        """
        if not client_config.enabled:
            self._failed_keys.discard(key)
            return False

        existing = self._clients.get(key)

        if existing is not None and getattr(existing, "is_connected", False):
            try:
                await asyncio.wait_for(existing.list_tools(), timeout=timeout)
                self._failed_keys.discard(key)
                self._clear_last_error(key)
                return True
            except Exception as exc:
                logger.debug(
                    "MCP client '%s' health probe failed: %s",
                    key,
                    exc,
                )
                await self._safe_close_client(key, existing)

        try:
            await self.replace_client(key, client_config, timeout=timeout)
            self._failed_keys.discard(key)
            self._clear_last_error(key)
            return True
        except Exception:
            self._failed_keys.add(key)
            return False

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
            self._set_last_error(key, asyncio.TimeoutError())
            await self._safe_close_client(key, new_client)
            raise
        except Exception as e:
            category, retryable = self.classify_exception(e)
            status_code, failed_url = self.extract_status_and_url(e)
            hint = self.remediation_hint(category)
            self._set_last_error(key, e)
            logger.warning(
                "Failed to connect MCP client '%s' "
                "(transport=%s, url=%s, category=%s, retryable=%s, "
                "status=%s, failed_url=%s, hint=%s): %s",
                key,
                client_config.transport,
                client_config.url or "<stdio>",
                category,
                retryable,
                status_code,
                failed_url,
                hint,
                self.describe_exception(e),
            )
            await self._safe_close_client(key, new_client)
            raise

        # 2. Swap and close old client inside lock
        async with self._lock:
            old_client = self._clients.get(key)
            self._clients[key] = new_client
            self._clear_last_error(key)

            if old_client is not None:
                logger.debug(f"Closing old MCP client: {key}")
                await self._safe_close_client(key, old_client)
            else:
                logger.debug(f"Added new MCP client: {key}")

    async def remove_client(self, key: str) -> None:
        """Remove and close a client.

        Args:
            key: Client identifier to remove
        """
        async with self._lock:
            old_client = self._clients.pop(key, None)
            self._last_errors.pop(key, None)

        if old_client is not None:
            logger.debug(f"Removing MCP client: {key}")
            await self._safe_close_client(key, old_client)

    async def close_all(self) -> None:
        """Close all MCP clients.

        Called during application shutdown.
        """
        async with self._lock:
            # Close in LIFO order: HttpStatefulClient teardown requires this
            # to avoid cross-task cancel-scope errors during async cleanup.
            clients_snapshot = list(self._clients.items())[::-1]
            self._clients.clear()
            self._last_errors.clear()

        logger.debug("Closing all MCP clients")
        for key, client in clients_snapshot:
            if client is not None:
                await self._safe_close_client(key, client)

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
        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
        except Exception as e:
            self._set_last_error(key, e)
            await self._safe_close_client(key, client)
            raise

        async with self._lock:
            self._clients[key] = client
            self._failed_keys.discard(key)
            self._clear_last_error(key)

    @staticmethod
    def _is_known_cancel_scope_close_error(exc: Exception) -> bool:
        text = str(exc)
        return (
            isinstance(exc, RuntimeError)
            and "Attempted to exit cancel scope in a different task" in text
        )

    async def _safe_close_client(self, key: str, client: Any) -> None:
        """Best-effort close with guards for known third-party race errors.

        In some streamable_http failure paths (e.g., upstream 503), closing an
        unconnected client may trigger an anyio RuntimeError in background
        tasks.
        We skip close for unconnected clients and downgrade known close races.
        """
        if client is None:
            return

        is_connected = bool(getattr(client, "is_connected", False))
        if not is_connected:
            logger.debug(
                "Skipping close for MCP client '%s' because "
                "it is not connected",
                key,
            )
            return

        try:
            await asyncio.wait_for(client.close(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout closing MCP client '%s'", key)
        except Exception as e:
            if self._is_known_cancel_scope_close_error(e):
                logger.debug(
                    "Ignored known MCP close race for '%s': %s",
                    key,
                    e,
                )
                return
            logger.warning(f"Error closing MCP client '{key}': {e}")

    @staticmethod
    def describe_exception(exc: BaseException, max_depth: int = 6) -> str:
        """Format exception with nested causes/contexts for log readability."""

        def _one(e: BaseException) -> str:
            details = f"{type(e).__name__}: {e}"
            response = getattr(e, "response", None)
            request = getattr(e, "request", None)
            status_code = getattr(response, "status_code", None)
            if status_code is not None:
                req_url = getattr(request, "url", None) or getattr(
                    response,
                    "url",
                    None,
                )
                details += f" [status={status_code}, url={req_url}]"
            return details

        parts = []
        seen = set()
        current: BaseException | None = exc
        depth = 0

        while (
            current is not None
            and depth < max_depth
            and id(current) not in seen
        ):
            seen.add(id(current))
            parts.append(_one(current))
            next_exc = getattr(current, "__cause__", None)
            if next_exc is None:
                next_exc = getattr(current, "__context__", None)
            current = next_exc
            depth += 1

        if current is not None and depth >= max_depth:
            parts.append("...")

        return " <- ".join(parts)

    @staticmethod
    def _iter_exception_chain(exc: BaseException, max_depth: int = 8):
        """Iterate through exception cause/context chain safely."""
        seen = set()
        current: BaseException | None = exc
        depth = 0
        while (
            current is not None
            and depth < max_depth
            and id(current) not in seen
        ):
            seen.add(id(current))
            yield current
            next_exc = getattr(current, "__cause__", None)
            if next_exc is None:
                next_exc = getattr(current, "__context__", None)
            current = next_exc
            depth += 1

    @classmethod
    def extract_status_and_url(
        cls,
        exc: BaseException,
    ) -> tuple[int | None, str | None]:
        """Extract first available HTTP status/url from exception chain."""
        for item in cls._iter_exception_chain(exc):
            response = getattr(item, "response", None)
            request = getattr(item, "request", None)
            status_code = getattr(response, "status_code", None)
            if status_code is None:
                continue

            req_url = getattr(request, "url", None) or getattr(
                response,
                "url",
                None,
            )
            return status_code, str(req_url) if req_url is not None else None

        return None, None

    @classmethod
    def classify_exception(cls, exc: BaseException) -> tuple[str, bool]:
        """Classify MCP connection errors for faster triage.

        Returns:
            (category, retryable)
        """
        category = "unknown"
        retryable = True

        status_code, _ = cls.extract_status_and_url(exc)
        if status_code in (401, 403):
            category, retryable = "auth", False
        elif status_code == 404:
            category, retryable = "endpoint_not_found", False
        elif status_code == 429:
            category, retryable = "rate_limited", True
        elif status_code is not None and 500 <= status_code <= 599:
            category, retryable = "server", True
        else:
            chain_text = " ".join(
                f"{type(item).__name__}: {item}"
                for item in cls._iter_exception_chain(exc)
            ).lower()

            if "session terminated" in chain_text:
                category, retryable = "session_terminated", True
            elif "timed out" in chain_text or "timeout" in chain_text:
                category, retryable = "timeout", True
            elif "connect" in chain_text and "error" in chain_text:
                category, retryable = "connectivity", True
            elif "ssl" in chain_text or "certificate" in chain_text:
                category, retryable = "tls", False

        return category, retryable

    @staticmethod
    def remediation_hint(category: str) -> str:
        """Return a short operator-facing remediation hint."""
        hints = {
            "auth": (
                "check Authorization token scope/expiry "
                "and server auth config"
            ),
            "endpoint_not_found": (
                "verify MCP endpoint path and reverse " "proxy routing"
            ),
            "rate_limited": (
                "reduce retry frequency or increase " "upstream rate limit"
            ),
            "server": (
                "check upstream server health/logs " "and dependency status"
            ),
            "session_terminated": (
                "check upstream session lifecycle " "and long-poll stability"
            ),
            "timeout": (
                "check network latency, upstream "
                "response time, and timeout settings"
            ),
            "connectivity": (
                "check DNS/network reachability/firewall "
                "between CoPaw and MCP host"
            ),
            "tls": "check certificate chain, hostname, and TLS settings",
            "unknown": (
                "inspect exception chain detail and "
                "upstream MCP server logs"
            ),
        }
        return hints.get(category, hints["unknown"])

    def _set_last_error(self, key: str, exc: BaseException) -> None:
        category, retryable = self.classify_exception(exc)
        status_code, failed_url = self.extract_status_and_url(exc)
        self._last_errors[key] = {
            "category": category,
            "retryable": retryable,
            "status": status_code,
            "failed_url": failed_url,
            "hint": self.remediation_hint(category),
            "detail": self.describe_exception(exc),
        }

    def _clear_last_error(self, key: str) -> None:
        self._last_errors.pop(key, None)

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

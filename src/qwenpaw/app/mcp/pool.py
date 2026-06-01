# -*- coding: utf-8 -*-
"""Shared MCP client pool for cross-agent reuse.

When multiple agents configure identical MCP servers (same command, args,
env, transport, url), they can share a single server process instead of
each spawning its own.  This drastically reduces resource usage when
running hundreds of agents on Windows (#4842).

Usage::

    pool = SharedMCPPool.instance()
    client = await pool.acquire(client_config)   # refcount++
    ...
    await pool.release(client_config)            # refcount--; close at 0
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...config.config import MCPClientConfig

logger = logging.getLogger(__name__)


def _config_fingerprint(config: "MCPClientConfig") -> str:
    """Compute a stable fingerprint for an MCP client configuration.

    Two configs with the same transport parameters will produce the same
    fingerprint, enabling client reuse across agents.  Fields like
    ``name``, ``description``, ``enabled``, and ``oauth`` are excluded
    because they don't affect the server process identity.
    """
    identity = {
        "transport": config.transport,
        "command": config.command,
        "args": list(config.args),
        "env": {k: os.path.expandvars(v) for k, v in config.env.items()},
        "cwd": config.cwd or "",
        "url": config.url,
        "headers": dict(config.headers or {}),
    }
    raw = json.dumps(identity, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class _PoolEntry:
    """A pooled MCP client with reference counting."""

    client: Any
    refcount: int = 0
    fingerprint: str = ""
    config_name: str = ""


class SharedMCPPool:
    """Process-global pool of shared MCP client instances.

    Thread-safety is provided by an asyncio.Lock (all callers run in the
    same event loop).  The pool is a singleton accessed via ``instance()``.
    """

    _instance: SharedMCPPool | None = None

    def __init__(self) -> None:
        self._entries: dict[str, _PoolEntry] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> SharedMCPPool:
        """Return the process-global pool singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing only)."""
        cls._instance = None

    async def acquire(
        self,
        client_config: "MCPClientConfig",
        *,
        builder: Any = None,
        timeout: float = 60.0,
    ) -> Any:
        """Acquire a shared MCP client for the given configuration.

        If a client with the same fingerprint already exists and is
        connected, its refcount is incremented and the existing client
        is returned.  Otherwise a new client is built, connected, and
        added to the pool.

        Args:
            client_config: MCP client configuration.
            builder: Callable(config) -> client.  Defaults to
                ``MCPClientManager._build_client``.
            timeout: Connection timeout in seconds.

        Returns:
            A connected MCP client instance (shared across agents).
        """
        fingerprint = _config_fingerprint(client_config)

        async with self._lock:
            entry = self._entries.get(fingerprint)
            if entry is not None and entry.client is not None:
                entry.refcount += 1
                logger.info(
                    "MCP pool: reusing '%s' (fp=%s, refcount=%d)",
                    entry.config_name,
                    fingerprint,
                    entry.refcount,
                )
                return entry.client

        # Build and connect outside the lock (may be slow).
        if builder is None:
            from .manager import MCPClientManager

            builder = getattr(MCPClientManager, "_build_client")

        client = builder(client_config)
        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
        except BaseException:
            await self._safe_close(client)
            raise

        async with self._lock:
            # Double-check: another task may have raced us.
            existing = self._entries.get(fingerprint)
            if existing is not None and existing.client is not None:
                # Another task won the race — discard ours.
                existing.refcount += 1
                logger.info(
                    "MCP pool: race resolved, reusing '%s' (fp=%s, "
                    "refcount=%d)",
                    existing.config_name,
                    fingerprint,
                    existing.refcount,
                )
                # Close our duplicate outside the lock.
                asyncio.create_task(self._safe_close(client))
                return existing.client

            self._entries[fingerprint] = _PoolEntry(
                client=client,
                refcount=1,
                fingerprint=fingerprint,
                config_name=client_config.name,
            )
            logger.info(
                "MCP pool: new client '%s' (fp=%s)",
                client_config.name,
                fingerprint,
            )
            return client

    async def release(
        self,
        client_config: "MCPClientConfig",
    ) -> None:
        """Release a reference to a shared MCP client.

        When the refcount reaches zero the client is closed and removed
        from the pool.

        Args:
            client_config: The same config used in ``acquire()``.
        """
        fingerprint = _config_fingerprint(client_config)
        client_to_close = None

        async with self._lock:
            entry = self._entries.get(fingerprint)
            if entry is None:
                logger.debug(
                    "MCP pool: release called for unknown fp=%s (already "
                    "closed?)",
                    fingerprint,
                )
                return

            entry.refcount -= 1
            logger.debug(
                "MCP pool: release '%s' (fp=%s, refcount=%d)",
                entry.config_name,
                fingerprint,
                entry.refcount,
            )

            if entry.refcount <= 0:
                client_to_close = entry.client
                del self._entries[fingerprint]

        # Close outside the lock.
        if client_to_close is not None:
            logger.info(
                "MCP pool: closing client (fp=%s, refcount reached 0)",
                fingerprint,
            )
            await self._safe_close(client_to_close)

    async def close_all(self) -> None:
        """Close all pooled clients (application shutdown)."""
        async with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()

        for entry in entries:
            if entry.client is not None:
                await self._safe_close(entry.client)

        logger.info("MCP pool: all clients closed")

    def stats(self) -> dict[str, int]:
        """Return pool statistics (for diagnostics / logging)."""
        return {
            "total_clients": len(self._entries),
            "total_refs": sum(e.refcount for e in self._entries.values()),
        }

    # ------------------------------------------------------------------

    @staticmethod
    async def _safe_close(client: Any) -> None:
        """Close a client, swallowing errors."""
        try:
            await client.close(ignore_errors=True)
        except Exception:
            logger.debug("Error closing pooled MCP client", exc_info=True)

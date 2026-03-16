# -*- coding: utf-8 -*-
"""Background task for refreshing MCP OAuth tokens.

This module provides automatic token refresh for MCP clients
that use OAuth authentication.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..mcp.manager import MCPClientManager

logger = logging.getLogger(__name__)

# Check interval in seconds (5 minutes)
TOKEN_REFRESH_INTERVAL = 300

# Refresh tokens when they expire within this many seconds (5 minutes)
TOKEN_REFRESH_THRESHOLD = 300


class MCPTokenRefresher:
    """Background task for refreshing MCP OAuth tokens.

    Periodically checks all MCP clients with OAuth tokens and
    refreshes them before they expire.
    """

    def __init__(
        self,
        mcp_manager: "MCPClientManager",
        interval: float = TOKEN_REFRESH_INTERVAL,
        threshold: float = TOKEN_REFRESH_THRESHOLD,
    ) -> None:
        """Initialize token refresher.

        Args:
            mcp_manager: MCP client manager instance
            interval: How often to check for expiring tokens (seconds)
            threshold: Refresh tokens expiring within this time (seconds)
        """
        self._mcp_manager = mcp_manager
        self._interval = interval
        self._threshold = threshold
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the background refresh task."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(
            self._refresh_loop(),
            name="mcp_token_refresher",
        )
        logger.debug(
            f"MCP token refresher started (interval={self._interval}s, "
            f"threshold={self._threshold}s)",
        )

    async def stop(self) -> None:
        """Stop the background refresh task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.debug("MCP token refresher stopped")

    async def _refresh_loop(self) -> None:
        """Main refresh loop."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                if self._running:
                    await self._check_and_refresh()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("MCP token refresh loop error")

    async def _check_and_refresh(self) -> None:
        """Check all clients and refresh expiring tokens."""
        from ...config import load_config, save_config
        from ..mcp.oauth import get_oauth_handler

        config = load_config()
        handler = get_oauth_handler()
        now = time.time()
        refreshed_count = 0

        for client_key, client_config in config.mcp.clients.items():
            # Skip if no OAuth discovery or no token
            if (
                not client_config.oauth_discovery
                or not client_config.oauth_token
            ):
                continue

            # Skip if no refresh token
            if not client_config.oauth_token.refresh_token:
                continue

            # Check if token is expiring soon
            expires_at = client_config.oauth_token.expires_at
            if expires_at - now > self._threshold:
                continue

            logger.info(
                f"MCP client '{client_key}' token expires in "
                f"{int(expires_at - now)}s, refreshing...",
            )

            try:
                new_token = await handler.refresh_token(
                    oauth_discovery=client_config.oauth_discovery,
                    oauth_token=client_config.oauth_token,
                )

                # Update config
                config.mcp.clients[client_key].oauth_token = new_token
                refreshed_count += 1

                # Rebuild the MCP client with new token
                try:
                    await self._mcp_manager.replace_client(
                        client_key,
                        config.mcp.clients[client_key],
                    )
                    logger.info(
                        f"MCP client '{client_key}' reconnected "
                        "with new token",
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to reconnect MCP client "
                        f"'{client_key}': {e}",
                    )

            except Exception as e:
                logger.warning(
                    f"Failed to refresh token for MCP client "
                    f"'{client_key}': {e}",
                )

        # Save config if any tokens were refreshed
        if refreshed_count > 0:
            save_config(config)
            logger.info(f"Refreshed {refreshed_count} MCP OAuth token(s)")

        # Cleanup expired pending auth requests
        await handler.cleanup_expired()


# Global singleton instance
_token_refresher: Optional[MCPTokenRefresher] = None


def get_token_refresher(
    mcp_manager: "MCPClientManager",
) -> MCPTokenRefresher:
    """Get or create the global token refresher instance.

    Args:
        mcp_manager: MCP client manager instance

    Returns:
        MCPTokenRefresher instance
    """
    global _token_refresher
    if _token_refresher is None:
        _token_refresher = MCPTokenRefresher(mcp_manager)
    return _token_refresher

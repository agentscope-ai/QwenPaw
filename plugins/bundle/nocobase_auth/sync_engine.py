# -*- coding: utf-8 -*-
"""Sync engine that keeps the local permission cache in sync with NocoBase."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .config import NocoBaseAuthConfig
from .nocobase_client import NocoBaseClient, NocoBaseClientError
from .permission_store import PermissionStore

logger = logging.getLogger(__name__)

_sync_engine: Optional["SyncEngine"] = None


def set_sync_engine(engine: Optional["SyncEngine"]) -> None:
    """Set the global sync engine instance used by routers."""
    global _sync_engine
    _sync_engine = engine


def get_sync_engine() -> Optional["SyncEngine"]:
    """Return the global sync engine instance, if initialized."""
    return _sync_engine


class SyncEngine:
    """Manages the NocoBase client and triggers full syncs."""

    def __init__(self, store: Optional[PermissionStore] = None):
        self.store = store or PermissionStore()
        self.config = self._load_config()
        self._client: Optional[NocoBaseClient] = None
        set_sync_engine(self)

    @staticmethod
    def _load_config() -> NocoBaseAuthConfig:
        """Load plugin config from disk."""
        return NocoBaseAuthConfig.load()

    def _save_config(self) -> None:
        """Persist current plugin config to disk."""
        self.config.save()

    def _get_client(self) -> Optional[NocoBaseClient]:
        if (
            not self.config.enabled
            or not self.config.base_url
            or not self.config.api_token
        ):
            return None
        if self._client is None:
            self._client = NocoBaseClient(
                base_url=self.config.base_url,
                api_token=self.config.api_token,
            )
        return self._client

    async def start(self) -> None:
        """Start the engine and perform an initial full sync."""
        if not self.config.enabled:
            logger.info("NocoBase auth is disabled; skipping initial sync")
            return
        logger.info("Starting NocoBase auth sync engine")
        await self.sync()

    async def stop(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def sync(self) -> Dict[str, Any]:
        """Perform a full sync from NocoBase.

        Returns:
            Dict with status, user_count, role_count, error.
        """
        client = self._get_client()
        if client is None:
            message = "NocoBase auth not configured"
            logger.warning(message)
            return {"status": "skipped", "error": message}

        try:
            users = await client.list_users(self.config.user_id_field)
            roles = await client.list_roles()
            role_map = self.store.get_role_channel_map()
            self.store.update_from_sync(users, roles, role_map, error="")
            status = {
                "status": "ok",
                "user_count": len(users),
                "role_count": len(roles),
                "error": "",
            }
            logger.info(
                "NocoBase sync completed: %s users, %s roles",
                len(users),
                len(roles),
            )
            return status
        except NocoBaseClientError as exc:
            error = str(exc)
            self.store.update_from_sync(
                [],
                [],
                self.store.get_role_channel_map(),
                error=error,
            )
            logger.error("NocoBase sync failed: %s", error)
            return {"status": "error", "error": error}
        except Exception as exc:
            error = f"Unexpected sync error: {exc}"
            self.store.update_from_sync(
                [],
                [],
                self.store.get_role_channel_map(),
                error=error,
            )
            logger.exception("NocoBase sync failed")
            return {"status": "error", "error": error}

    def update_config(self, config: NocoBaseAuthConfig) -> None:
        """Update runtime config and reset the client so new settings apply."""
        was_enabled = self.config.enabled if self.config else False
        self.config = config
        self._client = None
        self._save_config()

        # When the plugin is disabled, clear cached NocoBase permissions so
        # stale mappings do not continue to affect channel access.
        if was_enabled and not config.enabled:
            self.store.update_from_sync(
                [],
                [],
                {},
                error="Plugin disabled",
            )
            logger.info("NocoBase auth disabled; permission cache cleared")

    async def test_connection(self) -> Dict[str, Any]:
        """Test connectivity and authentication with NocoBase."""
        client = self._get_client()
        if client is None:
            return {"ok": False, "error": "NocoBase auth not configured"}
        try:
            ok = await client.health_check()
            if ok:
                return {"ok": True, "error": ""}
            return {"ok": False, "error": "NocoBase health check failed"}
        except NocoBaseClientError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("NocoBase connection test failed")
            return {"ok": False, "error": str(exc)}

    async def verify_user_token(
        self,
        user_token: str,
    ) -> Optional[Dict[str, Any]]:
        """Verify a NocoBase user token, delegating to the client.

        Returns ``None`` when the integration is not configured or the token
        is invalid; propagates :class:`NocoBaseClientError` on network errors
        so the resolver can avoid caching a "could not verify" outcome.
        """
        client = self._get_client()
        if client is None:
            return None
        return await client.verify_user_token(user_token)

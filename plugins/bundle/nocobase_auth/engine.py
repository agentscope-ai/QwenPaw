# -*- coding: utf-8 -*-
"""NocoBase engine: config + live identity/credential verification.

Replaces the former SyncEngine. Holds no local user mirror: users/roles are
queried live and identity is resolved per-request via the caller's own token.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .config import NocoBaseAuthConfig
from .nocobase_client import NocoBaseClient, NocoBaseClientError

logger = logging.getLogger(__name__)

_engine: Optional["NocoBaseEngine"] = None


def set_engine(engine: Optional["NocoBaseEngine"]) -> None:
    """Set the global engine instance used by routers."""
    global _engine  # noqa: PLW0603
    _engine = engine


def get_engine() -> Optional["NocoBaseEngine"]:
    """Return the global engine instance, if initialized."""
    return _engine


class NocoBaseEngine:
    """Owns config and NocoBase verification; no local mirror."""

    def __init__(
        self,
        config: Optional[NocoBaseAuthConfig] = None,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.config = (
            config if config is not None else NocoBaseAuthConfig.load()
        )
        self._transport = transport
        self._client: Optional[NocoBaseClient] = None
        set_engine(self)

    async def start(self) -> None:
        """Startup self-check: warn loudly if enabled but unreachable."""
        if not self.config.enabled:
            logger.info("NocoBase auth is disabled")
            return
        if not self.config.base_url:
            logger.warning(
                "NocoBase auth enabled but base_url is empty; console will "
                "fail closed until configured",
            )
            return
        ok = await self.test_connection()
        if not ok.get("ok"):
            logger.warning(
                "NocoBase auth enabled but connection check failed: %s. "
                "Console stays fail-closed until NocoBase is reachable.",
                ok.get("error"),
            )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _admin_client(self) -> Optional[NocoBaseClient]:
        """Client using the admin api_token; only for /users and /roles."""
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
                transport=self._transport,
            )
        return self._client

    async def update_config(self, config: NocoBaseAuthConfig) -> None:
        """Update runtime config; close the old admin client so new settings
        apply without leaking the old httpx client."""
        await self.stop()
        self.config = config
        self.config.save()

    async def verify_user_token(
        self,
        user_token: str,
    ) -> Optional[Dict[str, Any]]:
        """Verify a NocoBase user token via the caller's own token.

        Returns ``None`` when unconfigured or the token is invalid; propagates
        :class:`NocoBaseClientError` on network errors so the resolver avoids
        caching a "could not verify" outcome. Does NOT require api_token.
        """
        if not self.config.enabled or not self.config.base_url:
            return None
        client = NocoBaseClient(
            base_url=self.config.base_url,
            api_token="",  # auth:check uses the user token, not admin token
            transport=self._transport,
        )
        try:
            return await client.verify_user_token(user_token)
        finally:
            await client.close()

    async def authenticate_credentials(
        self,
        username: str,
        password: str,
    ) -> Optional[tuple[str, Optional[str]]]:
        """Authenticate NocoBase credentials; return ``(sender_id, token)``."""
        if not self.config.enabled or not self.config.base_url:
            return None
        client = NocoBaseClient(
            base_url=self.config.base_url,
            api_token=self.config.api_token,
            transport=self._transport,
        )
        try:
            user = await client.sign_in(
                username,
                password,
                authenticator=self.config.authenticator or "basic",
            )
            if user is None:
                return None
            sender_id = self._extract_login_identity(user)
            token = user.get("token")
            if not isinstance(token, str) or not token:
                token = None
            if not sender_id and token:
                checked = await client.verify_user_token(token)
                if checked:
                    sender_id = self._extract_login_identity(checked)
            if not sender_id:
                return None
            return sender_id, token
        finally:
            await client.close()

    def _extract_login_identity(self, payload: Dict[str, Any]) -> str:
        user = payload.get("user")
        row = user if isinstance(user, dict) else payload
        sender_id = NocoBaseClient.extract_sender_id(
            row,
            self.config.user_id_field,
        )
        if sender_id:
            return sender_id
        for fallback in ("username", "email", "phone", "nickname", "id"):
            sender_id = NocoBaseClient.extract_sender_id(row, fallback)
            if sender_id:
                return sender_id
        return ""

    async def test_connection(self) -> Dict[str, Any]:
        client = self._admin_client()
        if client is None:
            return {"ok": False, "error": "NocoBase auth not configured"}
        try:
            ok = await client.health_check()
            return (
                {"ok": True, "error": ""}
                if ok
                else {"ok": False, "error": "NocoBase health check failed"}
            )
        except NocoBaseClientError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("NocoBase connection test failed")
            return {"ok": False, "error": str(exc)}

    async def list_users(self) -> List[Dict[str, Any]]:
        """Live passthrough of NocoBase users (admin token). Raises if down."""
        client = self._admin_client()
        if client is None:
            raise RuntimeError("NocoBase auth not configured")
        return await client.list_users(self.config.user_id_field)

    async def list_roles(self) -> List[Dict[str, Any]]:
        """Live passthrough of NocoBase roles (admin token). Raises if down."""
        client = self._admin_client()
        if client is None:
            raise RuntimeError("NocoBase auth not configured")
        return await client.list_roles()

# -*- coding: utf-8 -*-
"""Yuanbao sign-token authentication.

Yuanbao bot gateway requires a token obtained via the sign-token REST API.
The token is then used for WebSocket AuthBind protobuf handshake.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

import aiohttp

from .constants import (
    DEFAULT_API_DOMAIN,
    RETRYABLE_SIGN_CODE,
    SIGN_MAX_RETRIES,
    SIGN_RETRY_DELAY_S,
    SIGN_TOKEN_PATH,
    TOKEN_REFRESH_MARGIN_S,
)

logger = logging.getLogger(__name__)


@dataclass
class SignTokenResult:
    """Result from sign-token API."""

    bot_id: str
    token: str
    source: str
    duration: int  # seconds until expiry
    product: str = "yuanbao"


@dataclass
class TokenCache:
    """Cached sign-token result with expiry tracking."""

    data: SignTokenResult
    expires_at: float  # epoch seconds
    _refresh_task: Optional[asyncio.Task] = field(default=None, repr=False)


def _compute_signature(
    nonce: str,
    timestamp: str,
    app_id: str,
    app_secret: str,
) -> str:
    """Compute HMAC-SHA256 signature for sign-token request.

    The plain text is: nonce + timestamp + appId + appSecret
    """
    plain = nonce + timestamp + app_id + app_secret
    return hmac.new(
        app_secret.encode("utf-8"),
        plain.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _generate_nonce() -> str:
    """Generate a random hex nonce."""
    return os.urandom(16).hex()


def _beijing_timestamp() -> str:
    """Generate a Beijing-timezone ISO timestamp for sign-token API."""
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    # Format: 2026-05-29T15:00:00+08:00 (no milliseconds)
    return now.strftime("%Y-%m-%dT%H:%M:%S+08:00")


class TokenManager:
    """Manages sign-token lifecycle: fetch, cache, auto-refresh."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        api_domain: str = DEFAULT_API_DOMAIN,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.api_domain = api_domain
        self._cache: Optional[TokenCache] = None
        self._fetch_lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_token(self) -> SignTokenResult:
        """Get a valid token, fetching a new one if needed."""
        if self._cache and self._cache.expires_at > time.time():
            return self._cache.data

        async with self._fetch_lock:
            # Double-check after acquiring lock
            if self._cache and self._cache.expires_at > time.time():
                return self._cache.data
            return await self._do_fetch()

    async def force_refresh(self) -> SignTokenResult:
        """Force a token refresh, clearing any cached token."""
        self._cache = None
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        async with self._fetch_lock:
            return await self._do_fetch()

    async def _do_fetch(self) -> SignTokenResult:
        """Execute the sign-token API call with retry logic."""
        domain = self.api_domain
        # Strip scheme if user accidentally included it
        if domain.startswith("https://"):
            domain = domain.removeprefix("https://")
        elif domain.startswith("http://"):
            domain = domain.removeprefix("http://")
        # Strip trailing slash
        domain = domain.rstrip("/")
        url = f"https://{domain}{SIGN_TOKEN_PATH}"
        session = await self._get_session()

        for attempt in range(SIGN_MAX_RETRIES + 1):
            nonce = _generate_nonce()
            timestamp = _beijing_timestamp()
            signature = _compute_signature(
                nonce,
                timestamp,
                self.app_id,
                self.app_secret,
            )

            body = {
                "app_key": self.app_id,
                "nonce": nonce,
                "signature": signature,
                "timestamp": timestamp,
            }

            retry_hint = (
                f" (retry {attempt}/{SIGN_MAX_RETRIES})" if attempt > 0 else ""
            )
            logger.info("yuanbao: signing token: url=%s%s", url, retry_hint)

            try:
                async with session.post(
                    url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if not response.ok:
                        raise RuntimeError(
                            f"sign-token HTTP error: {response.status} "
                            f"{response.reason}",
                        )
                    result = await response.json()
            except aiohttp.ClientError as exc:
                if attempt < SIGN_MAX_RETRIES:
                    logger.warning(
                        "yuanbao: sign-token network error: %s, retrying...",
                        exc,
                    )
                    await asyncio.sleep(SIGN_RETRY_DELAY_S)
                    continue
                raise RuntimeError(f"sign-token network error: {exc}") from exc

            code = result.get("code", -1)
            if code == 0:
                data = result["data"]
                token_result = SignTokenResult(
                    bot_id=data.get("bot_id", ""),
                    token=data.get("token", ""),
                    source=data.get("source", "bot"),
                    duration=data.get("duration", 0),
                    product=data.get("product", "yuanbao"),
                )
                logger.info(
                    "yuanbao: sign-token success: bot_id=%s",
                    token_result.bot_id,
                )

                # Cache with TTL
                if token_result.duration > 0:
                    ttl = token_result.duration
                    self._cache = TokenCache(
                        data=token_result,
                        expires_at=time.time() + ttl,
                    )
                    self._schedule_refresh(ttl)

                return token_result

            if code == RETRYABLE_SIGN_CODE and attempt < SIGN_MAX_RETRIES:
                logger.warning(
                    "yuanbao: sign-token retryable code=%s, retrying...",
                    code,
                )
                await asyncio.sleep(SIGN_RETRY_DELAY_S)
                continue

            raise RuntimeError(
                f"sign-token error: code={code}, msg={result.get('msg', '')}",
            )

        raise RuntimeError("sign-token failed: max retries exceeded")

    def _schedule_refresh(self, duration_seconds: int) -> None:
        """Schedule automatic token refresh before expiry."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()

        refresh_after = max(
            duration_seconds - TOKEN_REFRESH_MARGIN_S,
            60,
        )
        logger.info(
            "yuanbao: scheduled token refresh in %ss (duration=%ss)",
            refresh_after,
            duration_seconds,
        )

        async def _refresh():
            await asyncio.sleep(refresh_after)
            try:
                await self.force_refresh()
                logger.info("yuanbao: scheduled token refresh succeeded")
            except Exception as exc:
                logger.error(
                    "yuanbao: scheduled token refresh failed: %s",
                    exc,
                )

        self._refresh_task = asyncio.create_task(_refresh())

    async def get_auth_headers(self) -> Dict[str, str]:
        """Get auth headers for Yuanbao REST API calls (upload, etc.)."""
        token_data = await self.get_token()
        return {
            "X-ID": token_data.bot_id,
            "X-Token": token_data.token,
            "X-Source": token_data.source,
        }

    async def close(self) -> None:
        """Clean up resources."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        if self._session and not self._session.closed:
            await self._session.close()

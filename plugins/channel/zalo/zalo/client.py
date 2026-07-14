# -*- coding: utf-8 -*-
"""Async Zalo Bot API client.

Minimal, zero-dependency (beyond httpx) wrapper around the Zalo Bot HTTP API.
Used by ZaloChannel for polling mode.

Endpoints used (all under /bot<token>/):
    GET  /getMe           → bot info
    POST /sendMessage     → text reply
    POST /sendPhoto       → image attachment
    POST /sendSticker     → sticker
    POST /sendVoice       → voice message
    POST /sendChatAction  → typing indicator
    POST /getUpdates      → long-poll for new messages
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ZaloAPIError(Exception):
    """Raised when Zalo API returns an error."""

    def __init__(self, status_code: int, message: str, body: Any = None):
        self.status_code = status_code
        self.message = message
        self.body = body
        super().__init__(f"Zalo API {status_code}: {message}")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ZaloClient:
    """Async HTTP client for the Zalo Bot API.

    All methods are async and raise ZaloAPIError on non-2xx responses.

    Args:
        token: Zalo Bot API token (format: "OA_ID:TOKEN")
        base_url: Override the API base URL (default: Zalo Bot API)
        timeout: HTTP request timeout in seconds
    """

    BASE_URL = "https://bot.zalo.me/api"

    def __init__(
        self,
        token: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self._token = token
        self._base = (base_url or self.BASE_URL).rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the underlying httpx client."""
        if self._client is not None:
            return
        self._client = httpx.AsyncClient(timeout=self._timeout + 30)

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("ZaloClient not started — call start() first")
        return self._client

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        retries: int = 3,
    ) -> Dict[str, Any]:
        """Send an HTTP request to the Zalo API with retry on 5xx.

        Zalo Bot API uses a Telegram-style URL pattern:
            {base_url}/bot{token}/{endpoint}
        """
        url = f"{self._base}/bot{self._token}{path}"
        headers = {"Content-Type": "application/json"}

        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                resp = await self.client.request(
                    method, url, json=json_body, headers=headers
                )
                if 200 <= resp.status_code < 300:
                    return resp.json()
                if resp.status_code >= 500:
                    wait = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Zalo %s %s failed (attempt %d/%d): %s — retry in %.1fs",
                        method, path, attempt, retries, resp.text[:200], wait,
                    )
                    if attempt < retries:
                        import asyncio
                        await asyncio.sleep(wait)
                        continue
                raise ZaloAPIError(resp.status_code, resp.text[:200], resp.json() if resp.text else None)
            except ZaloAPIError:
                raise
            except Exception as e:
                last_error = e
                if attempt < retries:
                    wait = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Zalo %s %s network error (attempt %d/%d): %s",
                        method, path, attempt, retries, e,
                    )
                    import asyncio
                    await asyncio.sleep(wait)
                else:
                    raise ZaloAPIError(0, f"Network error: {e}") from e

        raise ZaloAPIError(0, f"All retries exhausted: {last_error}") from last_error

    # -- Bot info --

    async def get_me(self) -> Dict[str, Any]:
        """Get bot information. Returns ``{id, name, is_bot}``."""
        return await self._request("GET", "/getMe")

    # -- Messaging --

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a text message. Returns ``{message_id}``."""
        body: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            body["parse_mode"] = parse_mode
        return await self._request("POST", "/sendMessage", body)

    async def send_photo(
        self,
        chat_id: str,
        photo: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a photo by URL."""
        body: Dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption:
            body["caption"] = caption
        return await self._request("POST", "/sendPhoto", body)

    async def send_sticker(
        self,
        chat_id: str,
        sticker: str,
    ) -> Dict[str, Any]:
        """Send a sticker by ID/URL."""
        return await self._request("POST", "/sendSticker", {
            "chat_id": chat_id, "sticker": sticker,
        })

    async def send_voice(
        self,
        chat_id: str,
        voice_url: str,
    ) -> Dict[str, Any]:
        """Send a voice message by URL."""
        return await self._request("POST", "/sendVoice", {
            "chat_id": chat_id, "voice_url": voice_url,
        })

    # -- Chat Action (typing indicator) --

    async def send_chat_action(
        self,
        chat_id: str,
        action: str = "typing",
    ) -> Dict[str, Any]:
        """Show a temporary chat action (typing indicator).

        Args:
            chat_id: Recipient chat ID.
            action: Action type — ``"typing"`` (default) or ``"upload_photo"``.

        Returns:
            ``{"ok": true}`` on success.
        """
        return await self._request("POST", "/sendChatAction", {
            "chat_id": chat_id,
            "action": action,
        })

    # -- Polling --

    async def get_updates(
        self,
        offset: int = 0,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Long-poll for new updates (polling mode only).

        Returns ``{ok, result: [{update_id, message, ...}]}``.
        """
        return await self._request("POST", "/getUpdates", {
            "offset": offset,
            "timeout": timeout,
        })

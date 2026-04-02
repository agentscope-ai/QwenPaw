# -*- coding: utf-8 -*-
"""iLink Bot HTTP client for WeChat (WeChat personal account Bot API).

All iLink API endpoints live under https://ilinkai.weixin.qq.com.
Protocol: HTTP/JSON, no third-party SDK required.

Authentication flow:
1. GET /ilink/bot/get_bot_qrcode?bot_type=3  → qrcode + qrcode_img_content
2. Poll GET /ilink/bot/get_qrcode_status?qrcode=<qrcode> until confirmed
3. Save bot_token + baseurl from the confirmed response
4. Use bearer token for all subsequent requests
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

import httpx

from .utils import (
    aes_ecb_decrypt,
    aes_ecb_encrypt_bytes,
    generate_aes_key,
    make_headers,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
_CHANNEL_VERSION = "2.0.1"
# Long-poll hold time is up to 35 seconds (server-controlled)
_GETUPDATES_TIMEOUT = 45.0
_DEFAULT_TIMEOUT = 15.0


def _base_info() -> Dict[str, str]:
    return {"channel_version": _CHANNEL_VERSION}


class ILinkClient:
    """Async HTTP client for the WeChat iLink Bot API.

    Args:
        bot_token: Bearer token obtained after QR code login.
        base_url: iLink API base URL (defaults to ilinkai.weixin.qq.com).
    """

    def __init__(
        self,
        bot_token: str = "",
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self.bot_token = bot_token
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the underlying httpx client."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(_GETUPDATES_TIMEOUT),
        )

    async def stop(self) -> None:
        """Close the underlying httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self.base_url}/{path}"

    async def _get(self, path: str, params: Dict[str, Any] = None) -> Any:
        assert self._client is not None, "ILinkClient not started"
        headers = make_headers(self.bot_token)
        resp = await self._client.get(
            self._url(path),
            params=params or {},
            headers=headers,
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    async def _post(
        self,
        path: str,
        body: Dict[str, Any],
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> Any:
        assert self._client is not None, "ILinkClient not started"
        headers = make_headers(self.bot_token)
        resp = await self._client.post(
            self._url(path),
            json=body,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Auth APIs
    # ------------------------------------------------------------------

    async def get_bot_qrcode(self) -> Dict[str, Any]:
        """Fetch login QR code.

        Returns dict with keys:
            qrcode (str): QR code string to poll status.
            qrcode_img_content (str): Base64-encoded PNG image of QR code.
        """
        return await self._get("ilink/bot/get_bot_qrcode", {"bot_type": 3})

    async def get_qrcode_status(self, qrcode: str) -> Dict[str, Any]:
        """Poll QR code scan status.

        Returns dict with keys:
            status (str): "waiting" | "scanned" | "confirmed" | "expired"
            bot_token (str): Bearer token (only when status=="confirmed")
            baseurl (str): API base URL (only when status=="confirmed")
        """
        return await self._get(
            "ilink/bot/get_qrcode_status",
            {"qrcode": qrcode},
        )

    async def wait_for_login(
        self,
        qrcode: str,
        poll_interval: float = 1.5,
        max_wait: float = 300.0,
    ) -> Tuple[str, str]:
        """Block until QR code is confirmed or timeout.

        Args:
            qrcode: QR code string from get_bot_qrcode().
            poll_interval: Seconds between poll attempts.
            max_wait: Maximum seconds to wait.

        Returns:
            Tuple of (bot_token, base_url).

        Raises:
            TimeoutError: If login not confirmed within max_wait.
            RuntimeError: If QR code expired.
        """
        elapsed = 0.0
        while elapsed < max_wait:
            data = await self.get_qrcode_status(qrcode)
            status = data.get("status", "")
            if status == "confirmed":
                token = data.get("bot_token", "")
                base_url = data.get("baseurl", self.base_url)
                return token, base_url
            if status == "expired":
                raise RuntimeError(
                    "WeChat QR code expired, please retry login",
                )
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"WeChat QR code not scanned within {max_wait}s")

    # ------------------------------------------------------------------
    # Messaging APIs
    # ------------------------------------------------------------------

    async def getupdates(self, cursor: str = "") -> Dict[str, Any]:
        """Long-poll for incoming messages (holds up to 35 seconds).

        Args:
            cursor: get_updates_buf from previous response;
                empty on first call.

        Returns:
            Dict with keys:
                ret (int): 0 = success.
                msgs (list): List of WeixinMessage dicts (may be absent).
                get_updates_buf (str): Cursor for next call.
                longpolling_timeout_ms (int): Server-side hold time.
        """
        body: Dict[str, Any] = {
            "get_updates_buf": cursor,
            "base_info": {"channel_version": _CHANNEL_VERSION},
        }
        return await self._post(
            "ilink/bot/getupdates",
            body,
            timeout=_GETUPDATES_TIMEOUT,
        )

    async def sendmessage(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Send a message to a WeChat user.

        Args:
            msg: Message dict. Required fields:
                to_user_id (str): Recipient user ID (xxx@im.wechat).
                message_type (int): 2 = BOT.
                message_state (int): 2 = FINISH.
                context_token (str): Token from inbound message (REQUIRED).
                item_list (list): Content items.

        Returns:
            API response dict.
        """
        return await self._post(
            "ilink/bot/sendmessage",
            {"msg": msg, "base_info": {"channel_version": _CHANNEL_VERSION}},
        )

    async def send_text(
        self,
        to_user_id: str,
        text: str,
        context_token: str,
    ) -> Dict[str, Any]:
        """Convenience: send a plain text message.

        Args:
            to_user_id: Recipient user ID.
            text: Message text.
            context_token: context_token from the inbound message.

        Returns:
            API response dict.
        """
        return await self.sendmessage(
            {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": str(uuid.uuid4()),
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            },
        )

    async def getconfig(
        self,
        user_id: str,
        context_token: str,
    ) -> Dict[str, Any]:
        """Fetch bot config (e.g. typing_ticket).

        Args:
            user_id: User ID (ilink_user_id).
            context_token: Context token from inbound message.

        Returns:
            API response dict with typing_ticket.
        """
        return await self._post(
            "ilink/bot/getconfig",
            {
                "ilink_user_id": user_id,
                "context_token": context_token,
                "base_info": _base_info(),
            },
        )

    async def sendtyping(
        self,
        user_id: str,
        typing_ticket: str,
        status: int = 1,
    ) -> Dict[str, Any]:
        """Send "typing..." indicator to a user.

        Args:
            user_id: Recipient user ID (ilink_user_id).
            typing_ticket: Ticket from getconfig().
            status: 1 = start typing, 2 = stop typing.

        Returns:
            API response dict.
        """
        return await self._post(
            "ilink/bot/sendtyping",
            {
                "ilink_user_id": user_id,
                "typing_ticket": typing_ticket,
                "status": status,
                "base_info": _base_info(),
            },
        )

    # ------------------------------------------------------------------
    # Media helpers
    # ------------------------------------------------------------------

    async def download_media(
        self,
        url: str,
        aes_key_b64: str = "",
        encrypt_query_param: str = "",
    ) -> bytes:
        """Download a CDN media file and optionally decrypt it.

        iLink media files are stored on https://novac2c.cdn.weixin.qq.com/c2c.
        The 'url' field in image_item/file_item is a hex media-ID (not HTTP).
        The actual download URL is built from CDN base + encrypt_query_param.

        Args:
            url: CDN HTTP URL, or hex media-ID
                (ignored if encrypt_query_param).
            aes_key_b64: Base64-encoded AES-128 key; if empty, no decryption.
            encrypt_query_param: Query param from media.encrypt_query_param;
                if provided, use CDN base URL + this param to download.

        Returns:
            Decrypted (or raw) file bytes.
        """
        assert self._client is not None, "ILinkClient not started"

        if encrypt_query_param:
            cdn_base = "https://novac2c.cdn.weixin.qq.com/c2c"
            # Note: parameter name is "encrypted_query_param" (with 'd')
            enc = quote(encrypt_query_param, safe="")
            download_url = f"{cdn_base}/download?encrypted_query_param={enc}"
        elif url.startswith("http"):
            download_url = url
        else:
            raise ValueError(
                f"Cannot download media: no valid HTTP URL. "
                f"url={url[:40]!r}, encrypt_query_param empty.",
            )

        resp = await self._client.get(download_url, timeout=60.0)
        resp.raise_for_status()
        data = resp.content
        if aes_key_b64:
            data = aes_ecb_decrypt(data, aes_key_b64)
        return data

    async def getuploadurl(
        self,
        user_id: str,
        filekey: str,
        media_type: int,
        raw_size: int,
        encrypted_size: int,
        raw_md5: str,
        aes_key_hex: str,
    ) -> Dict[str, Any]:
        """Get CDN upload URL.

        Args:
            user_id: Target user ID.
            filekey: Random 32-char hex string.
            media_type: 1=image, 2=video, 3=file, 4=voice.
            raw_size: Original file size.
            encrypted_size: Encrypted file size.
            raw_md5: MD5 hash of original file.
            aes_key_hex: AES key as hex string.

        Returns:
            Dict with upload_param for CDN upload.
        """
        return await self._post(
            "ilink/bot/getuploadurl",
            {
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": user_id,
                "rawsize": raw_size,
                "rawfilemd5": raw_md5,
                "filesize": encrypted_size,
                "no_need_thumb": True,
                "aeskey": aes_key_hex,
                "base_info": _base_info(),
            },
        )

    async def upload_to_cdn(
        self,
        upload_param: str,
        filekey: str,
        encrypted_data: bytes,
    ) -> str:
        """Upload encrypted data to CDN.

        Args:
            upload_param: Upload parameter from getuploadurl.
            filekey: File key used in getuploadurl.
            encrypted_data: AES-encrypted file content.

        Returns:
            encrypt_query_param for sending in message.
        """
        assert self._client is not None, "ILinkClient not started"

        upload_url = (
            f"{_CDN_BASE_URL}/upload"
            f"?encrypted_query_param={quote(upload_param)}"
            f"&filekey={quote(filekey)}"
        )

        resp = await self._client.post(
            upload_url,
            content=encrypted_data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=60.0,
        )
        resp.raise_for_status()

        encrypt_query_param = resp.headers.get("x-encrypted-param")
        if not encrypt_query_param:
            raise RuntimeError(
                "CDN upload succeeded but x-encrypted-param header missing",
            )

        return encrypt_query_param

    async def upload_media(
        self,
        user_id: str,
        data: bytes,
        media_type: int,
    ) -> Dict[str, Any]:
        """Upload media file to CDN.

        Args:
            user_id: Target user ID.
            data: Raw file content.
            media_type: 1=image, 2=video, 3=file.

        Returns:
            Dict with:
                encrypt_query_param: For sending in message.
                aes_key: Base64-encoded AES key (for message).
                encrypted_size: Size of encrypted data.
        """
        # Generate AES key and encrypt
        aes_key = generate_aes_key()
        encrypted_data = aes_ecb_encrypt_bytes(data, aes_key)

        # Generate filekey and MD5
        filekey = os.urandom(16).hex()
        raw_md5 = hashlib.md5(data).hexdigest()

        # Get upload URL
        upload_info = await self.getuploadurl(
            user_id=user_id,
            filekey=filekey,
            media_type=media_type,
            raw_size=len(data),
            encrypted_size=len(encrypted_data),
            raw_md5=raw_md5,
            aes_key_hex=aes_key.hex(),
        )

        upload_param = upload_info.get("upload_param")
        if not upload_param:
            raise RuntimeError("getuploadurl did not return upload_param")

        # Upload to CDN
        encrypt_query_param = await self.upload_to_cdn(
            upload_param=upload_param,
            filekey=filekey,
            encrypted_data=encrypted_data,
        )

        # Encode aes_key as base64(hex) format for message
        import base64

        aes_key_b64 = base64.b64encode(aes_key.hex().encode()).decode()

        return {
            "encrypt_query_param": encrypt_query_param,
            "aes_key": aes_key_b64,
            "encrypted_size": len(encrypted_data),
        }

    def build_media_message(
        self,
        user_id: str,
        context_token: str,
        item_list: list,
    ) -> Dict[str, Any]:
        """Build a media message dict.

        Args:
            user_id: Target user ID.
            context_token: Context token from inbound message.
            item_list: List of message items.

        Returns:
            Message dict for sendmessage.
        """
        return {
            "from_user_id": "",
            "to_user_id": user_id,
            "client_id": str(uuid.uuid4()),
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": item_list,
        }

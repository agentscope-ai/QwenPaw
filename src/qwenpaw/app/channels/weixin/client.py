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
import base64
import hashlib
import logging
import secrets
import uuid
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

import httpx

from .utils import (
    aes_ecb_decrypt,
    aes_ecb_encrypt,
    make_headers,
)
from ....exceptions import ChannelError

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
_CHANNEL_VERSION = "2.0.1"
# Long-poll hold time is up to 35 seconds (server-controlled)
_GETUPDATES_TIMEOUT = 45.0
_DEFAULT_TIMEOUT = 15.0
# iLink holds QR-status polls up to ~30s; use a dedicated longer timeout
# so wait_for_login governs total wait time, not the transport.
_QRCODE_STATUS_TIMEOUT = 60.0


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

    async def _get(
        self,
        path: str,
        params: Dict[str, Any] = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> Any:
        if self._client is None:
            raise ChannelError(
                channel_name="weixin",
                message="ILinkClient not started",
            )
        headers = make_headers(self.bot_token)
        resp = await self._client.get(
            self._url(path),
            params=params or {},
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    async def _post(
        self,
        path: str,
        body: Dict[str, Any],
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> Any:
        if self._client is None:
            raise ChannelError(
                channel_name="wechat",
                message="ILinkClient not started",
            )
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
            timeout=_QRCODE_STATUS_TIMEOUT,
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
            try:
                data = await self.get_qrcode_status(qrcode)
            except httpx.ReadTimeout:
                logger.warning(
                    "weixin: QR status poll timed out, retrying…",
                )
                elapsed += poll_interval
                continue
            status = data.get("status", "")
            if status == "confirmed":
                token = data.get("bot_token", "")
                base_url = data.get("baseurl", self.base_url)
                return token, base_url
            if status == "expired":
                raise ChannelError(
                    channel_name="wechat",
                    message="WeChat QR code expired, please retry login",
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
        ilink_user_id: str = "",
        context_token: str = "",
    ) -> Dict[str, Any]:
        """Fetch bot config (e.g. typing_ticket).

        Args:
            ilink_user_id: User ID for the config request.
            context_token: Context token for the config request.

        Returns:
            API response dict.
        """
        body: Dict[str, Any] = {}
        if ilink_user_id:
            body["ilink_user_id"] = ilink_user_id
        if context_token:
            body["context_token"] = context_token
        body["base_info"] = {"channel_version": _CHANNEL_VERSION}
        return await self._post("ilink/bot/getconfig", body)

    async def sendtyping(
        self,
        to_user_id: str,
        typing_ticket: str,
        status: int = 1,
    ) -> Dict[str, Any]:
        """Send "typing..." indicator to a user.

        Args:
            to_user_id: Recipient user ID.
            typing_ticket: Ticket from getconfig().
            status: 1 = start typing, 2 = stop typing.

        Returns:
            API response dict.
        """
        logger.debug(
            f"ILinkClient sendtyping: to_user_id={to_user_id[:20]}..., "
            f"ticket={typing_ticket[:20]}..., status={status}",
        )
        resp = await self._post(
            "ilink/bot/sendtyping",
            {
                "ilink_user_id": to_user_id,
                "typing_ticket": typing_ticket,
                "status": status,
                "base_info": {"channel_version": _CHANNEL_VERSION},
            },
        )
        ret = resp.get("ret", -1)
        errcode = resp.get("errcode", -1)
        logger.debug(
            f"ILinkClient sendtyping response: ret={ret}, "
            f"errcode={errcode}",
        )
        return resp

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
        if self._client is None:
            raise ChannelError(
                channel_name="wechat",
                message="ILinkClient not started",
            )

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
        filekey: str,
        media_type: int,
        to_user_id: str,
        rawsize: int,
        rawfilemd5: str,
        filesize: int,
        aeskey: str,
        no_need_thumb: bool = True,
    ) -> Dict[str, Any]:
        """Get upload URL and parameters for a media file.

        Args:
            filekey: 16-byte random hex string (unique file identifier).
            media_type: 1=image, 2=video, 3=file, 4=voice.
            to_user_id: Recipient user ID.
            rawsize: Original file size in bytes.
            rawfilemd5: MD5 hash of original file (32 hex chars).
            filesize: Encrypted file size (after AES-ECB PKCS7 padding).
            aeskey: 32-char hex string (16-byte AES key).
            no_need_thumb: Whether to skip thumbnail generation.

        Returns:
            Dict with keys:
                upload_param (str): Encrypted upload parameters.
                upload_full_url (str): Complete upload URL.
        """
        body: Dict[str, Any] = {
            "filekey": filekey,
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": rawsize,
            "rawfilemd5": rawfilemd5,
            "filesize": filesize,
            "aeskey": aeskey,
            "no_need_thumb": no_need_thumb,
            "base_info": {"channel_version": _CHANNEL_VERSION},
        }
        return await self._post("ilink/bot/getuploadurl", body)

    async def upload_media(
        self,
        file_path: str,
        media_type: int,
        to_user_id: str,
    ) -> Dict[str, Any]:
        """Upload and encrypt a media file to WeChat CDN.

        This is a convenience method that:
        1. Generates AES key and filekey
        2. Calculates MD5 and sizes
        3. Encrypts the file with AES-128-ECB
        4. Gets upload URL from getuploadurl
        5. Uploads encrypted file to CDN
        6. Returns the download parameters needed for sendmessage

        Args:
            file_path: Local path to the file to upload.
            media_type: 1=image, 2=video, 3=file, 4=voice.
            to_user_id: Recipient user ID.

        Returns:
            Dict with keys:
                encrypt_query_param (str): For media.encrypt_query_param.
                aes_key_b64 (str): Base64-encoded AES key for media.aes_key.
                filesize (int): Encrypted file size.
        """
        if self._client is None:
            raise ChannelError(
                channel_name="wechat",
                message="ILinkClient not started",
            )

        # Read original file
        with open(file_path, "rb") as f:
            raw_data = f.read()

        rawsize = len(raw_data)
        rawfilemd5 = hashlib.md5(raw_data).hexdigest()

        # Generate AES key and filekey
        # Generate 16 random bytes for AES key
        aes_key_raw_bytes = secrets.token_bytes(16)
        # Convert to hex string for API call (32 hex chars)
        aes_key_hex = aes_key_raw_bytes.hex()
        # For message, we need base64(hex_string) -
        # following picoclaw's encodeWeixinOutboundAESKey
        aes_key_for_msg = base64.b64encode(aes_key_hex.encode()).decode()
        # For encryption, use base64 encoding of raw key
        aes_key_b64_for_encrypt = base64.b64encode(aes_key_raw_bytes).decode()
        # filekey: 16 bytes random hex
        filekey = secrets.token_hex(16)

        # Encrypt file with AES-128-ECB + PKCS7
        encrypted_data = aes_ecb_encrypt(raw_data, aes_key_b64_for_encrypt)
        filesize = len(encrypted_data)

        # Get upload URL
        upload_resp = await self.getuploadurl(
            filekey=filekey,
            media_type=media_type,
            to_user_id=to_user_id,
            rawsize=rawsize,
            rawfilemd5=rawfilemd5,
            filesize=filesize,
            aeskey=aes_key_hex,  # Send hex-encoded key to API
        )

        logger.debug(f"getuploadurl response: {upload_resp}")
        upload_url = upload_resp.get("upload_full_url", "")
        if not upload_url:
            # API might return upload_param instead,
            # need to construct URL manually
            upload_param = upload_resp.get("upload_param", "")
            if upload_param:
                cdn_base = "https://novac2c.cdn.weixin.qq.com/c2c"
                enc_param = quote(upload_param, safe="")
                # Add filekey as query parameter
                # (required by CDN for validation)
                upload_url = (
                    f"{cdn_base}/upload?encrypted_query_param={enc_param}"
                    f"&filekey={filekey}"
                )
                logger.debug(
                    "Constructed upload URL from upload_param "
                    f"with filekey={filekey}",
                )
            else:
                raise ValueError(
                    "No upload_full_url or upload_param in "
                    f"getuploadurl response: {upload_resp}",
                )

        # Upload encrypted file to CDN
        # Note: Don't include auth headers when using upload_param -
        # the param itself is encrypted
        headers = {
            "Content-Type": "application/octet-stream",
        }

        logger.debug(
            f"Uploading to URL: {upload_url[:100]}...",
        )
        resp = await self._client.post(
            upload_url,
            content=encrypted_data,
            headers=headers,
            timeout=120.0,
        )
        logger.debug(
            f"Upload response status: {resp.status_code}, "
            f"headers: {dict(resp.headers)}",
        )
        resp.raise_for_status()

        # Get download parameters from response header
        # Note: header name might be case-sensitive
        encrypt_query_param = resp.headers.get(
            "x-encrypted-param",
            "",
        ) or resp.headers.get(
            "X-Encrypted-Param",
            "",
        )
        logger.info(
            "Got encrypt_query_param from headers: "
            f"{encrypt_query_param[:50] if encrypt_query_param else 'EMPTY'}"
            "...",
        )

        # Validate encrypt_query_param before returning
        if not encrypt_query_param:
            logger.error(
                "upload_media: encrypt_query_param is empty! "
                "Sent files will appear blank on receiver side. "
                f"Response headers: {dict(resp.headers)}",
            )
            raise ValueError(
                "upload_media failed: CDN did not return "
                "encrypt_query_param in response headers. "
                "Files cannot be sent without this parameter.",
            )

        return {
            "encrypt_query_param": encrypt_query_param,
            "aes_key_b64": aes_key_for_msg,  # base64(hex_string) for message
            "filesize": filesize,
        }

    async def send_file(
        self,
        to_user_id: str,
        file_path: str,
        filename: str,
        context_token: str,
    ) -> Dict[str, Any]:
        """Send a file message.

        Args:
            to_user_id: Recipient user ID.
            file_path: Local path to the file.
            filename: Display filename.
            context_token: Context token from inbound message.

        Returns:
            API response dict.
        """
        # Upload file
        upload_result = await self.upload_media(file_path, 3, to_user_id)

        # Send file message
        return await self.sendmessage(
            {
                "to_user_id": to_user_id,
                "client_id": str(uuid.uuid4()),
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {
                        "type": 4,
                        "file_item": {
                            "media": {
                                "encrypt_query_param": upload_result[
                                    "encrypt_query_param"
                                ],
                                "aes_key": upload_result["aes_key_b64"],
                                "encrypt_type": 1,
                            },
                            "file_name": filename,
                            "len": str(upload_result["filesize"]),
                        },
                    },
                ],
            },
        )

    async def send_image(
        self,
        to_user_id: str,
        image_path: str,
        context_token: str,
    ) -> Dict[str, Any]:
        """Send an image message.

        Args:
            to_user_id: Recipient user ID.
            image_path: Local path to the image file.
            context_token: Context token from inbound message.

        Returns:
            API response dict.
        """
        # Upload image
        upload_result = await self.upload_media(image_path, 1, to_user_id)

        # Log media parameters for debugging
        encrypt_preview = (
            upload_result["encrypt_query_param"][:50]
            if upload_result["encrypt_query_param"]
            else "EMPTY"
        )
        logger.info(
            f"Image media params: encrypt_query_param={encrypt_preview}..., "
            f"aes_key={upload_result['aes_key_b64'][:20]}..., "
            f"filesize={upload_result['filesize']}",
        )

        # Send image message
        return await self.sendmessage(
            {
                "to_user_id": to_user_id,
                "client_id": str(uuid.uuid4()),
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {
                        "type": 2,
                        "image_item": {
                            "media": {
                                "encrypt_query_param": upload_result[
                                    "encrypt_query_param"
                                ],
                                "aes_key": upload_result["aes_key_b64"],
                                "encrypt_type": 1,
                            },
                            "mid_size": upload_result["filesize"],
                        },
                    },
                ],
            },
        )

    async def send_video(
        self,
        to_user_id: str,
        video_path: str,
        context_token: str,
    ) -> Dict[str, Any]:
        """Send a video message.

        Args:
            to_user_id: Recipient user ID.
            video_path: Local path to the video file.
            context_token: Context token from inbound message.

        Returns:
            API response dict.
        """
        # Upload video
        upload_result = await self.upload_media(video_path, 2, to_user_id)

        # Send video message
        return await self.sendmessage(
            {
                "to_user_id": to_user_id,
                "client_id": str(uuid.uuid4()),
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {
                        "type": 5,
                        "video_item": {
                            "media": {
                                "encrypt_query_param": upload_result[
                                    "encrypt_query_param"
                                ],
                                "aes_key": upload_result["aes_key_b64"],
                                "encrypt_type": 1,
                            },
                        },
                    },
                ],
            },
        )

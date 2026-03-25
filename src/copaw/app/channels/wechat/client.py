# -*- coding: utf-8 -*-
"""HTTP client for Wechat protocol."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple
from urllib.parse import quote

import httpx

from .types import UploadResult

logger = logging.getLogger(__name__)

# OpenClaw weixin default (c2c CDN); not the ilink JSON API host.
DEFAULT_WECHAT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"


class WechatApiError(RuntimeError):
    """Raised when API returns non-success semantics."""


class WechatProtocolError(RuntimeError):
    """Raised when payload or protocol requirements are violated."""


class WechatApiClient:
    """Minimal async client for Wechat JSON APIs."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        uin: str = "",
        timeout_ms: int = 15_000,
        long_poll_timeout_ms: int = 35_000,
        cdn_base_url: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._token = (token or "").strip()
        self._uin = (uin or "").strip()
        self._fallback_uin = str(secrets.randbelow(2**32))
        self._timeout_ms = max(1_000, timeout_ms)
        self._long_poll_timeout_ms = max(5_000, long_poll_timeout_ms)
        raw_cdn = (cdn_base_url or "").strip().rstrip("/")
        self._cdn_base_url = raw_cdn or DEFAULT_WECHAT_CDN_BASE_URL
        if not self._uin:
            logger.warning(
                "wechat uin is empty; using instance-stable fallback identity",
            )
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout_ms / 1000.0),
        )
        # CDN origin differs from ilink API; use a bare client for CDN URLs.
        self._http_cdn = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout_ms / 1000.0),
            follow_redirects=True,
        )

    async def close(self) -> None:
        """Close underlying HTTP client."""
        await self._http.aclose()
        await self._http_cdn.aclose()

    async def get_updates(self, get_updates_buf: str) -> Dict[str, Any]:
        """Long-poll updates from backend."""
        payload = {"get_updates_buf": get_updates_buf or ""}
        return await self._post_json(
            endpoint="ilink/bot/getupdates",
            payload=payload,
            timeout_ms=self._long_poll_timeout_ms,
            allow_timeout=True,
            allow_api_error=True,
        )

    async def send_message(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Send a message payload."""
        return await self._post_json(
            endpoint="ilink/bot/sendmessage",
            payload=body,
        )

    async def get_upload_url(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Get upload params for CDN media upload."""
        return await self._post_json(
            endpoint="ilink/bot/getuploadurl",
            payload=body,
        )

    async def get_config(
        self,
        *,
        ilink_user_id: str,
        context_token: str = "",
    ) -> Dict[str, Any]:
        """Get config payload, including typing_ticket."""
        return await self._post_json(
            endpoint="ilink/bot/getconfig",
            payload={
                "ilink_user_id": ilink_user_id,
                "context_token": context_token,
            },
        )

    async def send_typing(
        self,
        *,
        ilink_user_id: str,
        typing_ticket: str,
        status: int,
    ) -> Dict[str, Any]:
        """Send typing state."""
        return await self._post_json(
            endpoint="ilink/bot/sendtyping",
            payload={
                "ilink_user_id": ilink_user_id,
                "typing_ticket": typing_ticket,
                "status": status,
            },
        )

    async def upload_media(
        self,
        *,
        local_path: Path,
        to_user_id: str,
        media_type: int,
    ) -> UploadResult:
        """Upload a local media file to CDN and return reference tokens."""
        if not local_path.is_file():
            raise WechatProtocolError(f"media file not found: {local_path}")
        raw = local_path.read_bytes()
        rawsize = len(raw)
        rawmd5 = hashlib.md5(raw).hexdigest()
        aes_key = secrets.token_bytes(16)
        ciphertext = _encrypt_aes_128_ecb(raw, aes_key)
        filekey = secrets.token_hex(16)

        upload_resp = await self.get_upload_url(
            {
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": to_user_id,
                "rawsize": rawsize,
                "rawfilemd5": rawmd5,
                "filesize": len(ciphertext),
                "no_need_thumb": True,
                "aeskey": aes_key.hex(),
            },
        )
        upload_param = str(upload_resp.get("upload_param") or "")
        if not upload_param:
            raise WechatProtocolError(
                "getuploadurl returned empty upload_param",
            )

        upload_url = self._build_cdn_upload_url(
            upload_param=upload_param,
            filekey=filekey,
        )
        response = await self._http_cdn.post(
            upload_url,
            content=ciphertext,
            headers={"Content-Type": "application/octet-stream"},
        )
        if response.status_code >= 400:
            raise WechatApiError(
                f"cdn upload failed: status={response.status_code}",
            )
        encrypted_query_param = response.headers.get(
            "x-encrypted-param",
            "",
        ).strip()
        if not encrypted_query_param:
            raise WechatProtocolError("cdn upload missing x-encrypted-param")

        return UploadResult(
            encrypted_query_param=encrypted_query_param,
            aes_key_b64=base64.b64encode(aes_key).decode("utf-8"),
            file_size=rawsize,
            file_size_cipher=len(ciphertext),
        )

    async def _post_json(
        self,
        *,
        endpoint: str,
        payload: Dict[str, Any],
        timeout_ms: Optional[int] = None,
        allow_timeout: bool = False,
        allow_api_error: bool = False,
    ) -> Dict[str, Any]:
        merged_payload = dict(payload)
        merged_payload["base_info"] = {
            "channel_version": "python-copaw-wechat",
        }
        body = httpx.Request(
            method="POST",
            url=self._base_url,
            json=merged_payload,
        ).read()
        headers = self._build_headers(content_length=len(body))
        timeout = timeout_ms if timeout_ms is not None else self._timeout_ms

        try:
            response = await self._http.post(
                endpoint,
                json=merged_payload,
                headers=headers,
                timeout=httpx.Timeout(timeout / 1000.0),
            )
        except httpx.TimeoutException:
            if allow_timeout:
                return {
                    "ret": 0,
                    "msgs": [],
                    "get_updates_buf": payload.get("get_updates_buf", ""),
                }
            raise

        if response.status_code >= 400:
            raise WechatApiError(
                f"{endpoint} http status={response.status_code}"
                f" body={response.text[:300]}",
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise WechatProtocolError(
                f"{endpoint} returned invalid json",
            ) from exc
        if not isinstance(data, dict):
            raise WechatProtocolError(f"{endpoint} returned non-object json")
        ret = data.get("ret")
        if ret not in (None, 0) and not allow_api_error:
            errcode = data.get("errcode")
            errmsg = data.get("errmsg") or "unknown error"
            raise WechatApiError(
                f"{endpoint} ret={ret} errcode={errcode} errmsg={errmsg}",
            )
        return data

    def _build_headers(self, *, content_length: int) -> Dict[str, str]:
        uin_header = self._encoded_uin()
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Content-Length": str(content_length),
            "X-WECHAT-UIN": uin_header,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _encoded_uin(self) -> str:
        raw = self._uin or self._fallback_uin
        return base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    def _build_cdn_upload_url(self, *, upload_param: str, filekey: str) -> str:
        if upload_param.startswith("http://") or upload_param.startswith(
            "https://",
        ):
            if "filekey=" in upload_param:
                return upload_param
            sep = "&" if "?" in upload_param else "?"
            return f"{upload_param}{sep}filekey={quote(filekey)}"

        cdn_base = self._cdn_base_url
        return (
            f"{cdn_base}/upload?encrypted_query_param={quote(upload_param)}"
            f"&filekey={quote(filekey)}"
        )

    async def _fetch_cdn_ciphertext(self, encrypted_query_param: str) -> bytes:
        """GET (or POST) encrypted blob from WeChat c2c CDN ``/download``."""
        eq = (encrypted_query_param or "").strip()
        if not eq:
            raise WechatProtocolError(
                "empty encrypted_query_param for download",
            )

        base = self._cdn_base_url.rstrip("/")
        q = f"encrypted_query_param={quote(eq)}"
        url = f"{base}/download?{q}"
        last_status: Optional[int] = None
        for do_post in (False, True):
            try:
                if do_post:
                    r = await self._http_cdn.post(
                        url,
                        content=b"",
                        headers={"Content-Type": "application/octet-stream"},
                    )
                else:
                    r = await self._http_cdn.get(url)
                last_status = r.status_code
                if r.status_code < 400:
                    return r.content
            except httpx.HTTPError:
                continue
        msg = (
            f"cdn download failed: status={last_status}. "
            f"CDN base={base}. "
            "Override channels.wechat.cdn_base_url if needed."
        )
        raise WechatApiError(msg)

    async def download_cdn_file(
        self,
        *,
        encrypted_query_param: str,
        aes_key_b64_or_hex: Any,
    ) -> bytes:
        """Fetch CDN ciphertext; decrypt with AES-128-ECB PKCS7."""
        key = _parse_wechat_aes_key(aes_key_b64_or_hex)
        if key is None:
            logger.warning(
                "wechat aes_key parse failed: type=%s",
                type(aes_key_b64_or_hex).__name__,
            )
            raise WechatProtocolError(
                "invalid or missing aes_key for CDN download",
            )

        ciphertext = await self._fetch_cdn_ciphertext(encrypted_query_param)
        return _decrypt_aes_128_ecb(ciphertext, key)


# Prefer parent ``aeskey`` over ``media.aes_key`` (often base64-wrapped hex).
_INBOUND_AES_KEY_NAMES: Tuple[str, ...] = (
    "aeskey",
    "aesKey",
    "AesKey",
    "aes_key",
    "aes_key_b64",
    "aeskey_b64",
    "aes",
)


def extract_inbound_aes_key(*sources: Optional[Dict[str, Any]]) -> Any:
    """Return first usable aes key value from parent / media / item dicts."""
    for src in sources:
        if not isinstance(src, dict):
            continue
        for name in _INBOUND_AES_KEY_NAMES:
            v = src.get(name)
            if v is None:
                continue
            if isinstance(v, dict):
                v = (
                    v.get("value")
                    or v.get("data")
                    or v.get("aes_key")
                    or v.get("aeskey")
                )
            if v is None:
                continue
            if isinstance(v, str):
                s = v.strip()
                if not s or s.lower() in ("none", "null", "undefined"):
                    continue
                return v
            if isinstance(v, (bytes, bytearray, list, tuple)):
                return v
            return v
    return None


def _decoded_b64_to_aes_key(decoded: bytes) -> Optional[bytes]:
    """Map base64-decoded blob to 16-byte AES key if possible."""
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        try:
            txt = decoded.decode("ascii")
        except UnicodeDecodeError:
            return None
        if len(txt) == 32 and all(c in "0123456789abcdefABCDEF" for c in txt):
            return bytes.fromhex(txt)
    return None


def _try_b64decode_key(padded: str) -> Optional[bytes]:
    """Try standard and url-safe base64 decode of padded string."""
    for decoded in (
        _safe_b64decode(padded, use_urlsafe=False),
        _safe_b64decode(padded, use_urlsafe=True),
    ):
        if decoded is None:
            continue
        key = _decoded_b64_to_aes_key(decoded)
        if key is not None:
            return key
    return None


def _safe_b64decode(padded: str, *, use_urlsafe: bool) -> Optional[bytes]:
    try:
        if use_urlsafe:
            return base64.urlsafe_b64decode(padded)
        return base64.b64decode(padded)
    except Exception:
        return None


def _parse_wechat_aes_key_from_string(s: str) -> Optional[bytes]:
    """Parse hex, 16-byte utf-8, or base64 forms."""
    hex_body = s[2:] if s.lower().startswith("0x") else s
    hex_clean = "".join(c for c in hex_body if c in "0123456789abcdefABCDEF")
    if len(hex_clean) >= 32:
        try:
            out = bytes.fromhex(hex_clean[:32])
            if len(out) == 16:
                return out
        except ValueError:
            pass

    utf = s.encode("utf-8")
    if len(utf) == 16:
        return utf

    compact = "".join(s.split())
    for cand in (s, compact):
        if not cand:
            continue
        pad = (-len(cand)) % 4
        padded = cand + ("=" * pad)
        key = _try_b64decode_key(padded)
        if key is not None:
            return key
    return None


def _parse_wechat_aes_key_sequence(raw: Sequence[Any]) -> Optional[bytes]:
    if len(raw) != 16:
        return None
    try:
        return bytes(int(x) & 0xFF for x in raw)
    except (TypeError, ValueError):
        return None


def _parse_wechat_aes_key(raw: Any) -> Optional[bytes]:
    """Parse inbound AES-128 key (hex, base64, utf-8, or raw bytes)."""
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw) if len(raw) == 16 else None
    if isinstance(raw, (list, tuple)):
        return _parse_wechat_aes_key_sequence(raw)

    s = str(raw).strip()
    if not s or s.lower() in ("none", "null", "undefined"):
        return None
    return _parse_wechat_aes_key_from_string(s)


def _crypto_import_ciphers():
    """Import cryptography AES-ECB helpers (lazy)."""
    try:
        from cryptography.hazmat.primitives import padding as padding_mod
        from cryptography.hazmat.primitives.ciphers import (
            Cipher,
            algorithms,
            modes,
        )
    except ImportError as exc:
        raise WechatProtocolError(
            "cryptography package is required for Wechat media CDN",
        ) from exc
    return padding_mod, Cipher, algorithms, modes


def _encrypt_aes_128_ecb(plain: bytes, key: bytes) -> bytes:
    """Encrypt bytes with AES-128-ECB and PKCS7 padding."""
    if len(key) != 16:
        raise WechatProtocolError("AES-128 key must be 16 bytes")
    padding_mod, Cipher, algorithms, modes = _crypto_import_ciphers()
    padder = padding_mod.PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _decrypt_aes_128_ecb(ciphertext: bytes, key: bytes) -> bytes:
    """Decrypt bytes with AES-128-ECB and PKCS7 unpadding."""
    if len(key) != 16:
        raise WechatProtocolError("AES-128 key must be 16 bytes")
    padding_mod, Cipher, algorithms, modes = _crypto_import_ciphers()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding_mod.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()

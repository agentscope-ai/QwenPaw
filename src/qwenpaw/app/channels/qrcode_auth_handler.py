# -*- coding: utf-8 -*-
"""Unified QR code authorization handlers for channels.

Each channel that supports QR-code-based login/authorization implements a
concrete ``QRCodeAuthHandler`` and registers it in ``QRCODE_AUTH_HANDLERS``.
The router in *config.py* exposes two generic endpoints that delegate to
the appropriate handler based on the ``{channel}`` path parameter.

Typical flow
------------
1. ``GET /config/channels/{channel}/qrcode``
   → calls ``handler.fetch_qrcode(request)``
   → returns ``{"qrcode_img": "<base64 PNG>", "poll_token": "..."}``

2. ``GET /config/channels/{channel}/qrcode/status?token=...``
   → calls ``handler.poll_status(token, request)``
   → returns ``{"status": "...", "credentials": {...}}``
"""

from __future__ import annotations

import base64
import io
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Tuple

import segno
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, Request

from ...constant import PROJECT_NAME

logger = logging.getLogger(__name__)


@dataclass
class QRCodeResult:
    """Value object returned by ``fetch_qrcode``."""

    scan_url: str
    poll_token: str


@dataclass
class PollResult:
    """Value object returned by ``poll_status``."""

    status: str
    credentials: Dict[str, Any]


class QRCodeAuthHandler(ABC):
    """Abstract base class for channel QR code authorization."""

    @abstractmethod
    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        """Obtain the scan URL and a token used for subsequent polling."""

    @abstractmethod
    async def poll_status(self, token: str, request: Request) -> PollResult:
        """Check whether the user has scanned & confirmed authorization."""


def generate_qrcode_image(scan_url: str) -> str:
    """Generate a base64-encoded PNG QR code image from *scan_url*."""
    try:
        qr_code = segno.make(scan_url, error="M")
        buf = io.BytesIO()
        qr_code.save(buf, kind="png", scale=6, border=2)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"QR code image generation failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# WeChat (iLink) handler
# ---------------------------------------------------------------------------


class WeChatQRCodeAuthHandler(QRCodeAuthHandler):
    """QR code auth handler for WeChat iLink Bot login."""

    async def _get_base_url(self, request: Request) -> str:
        from ..channels.wechat.client import _DEFAULT_BASE_URL

        try:
            from ..agent_context import get_agent_for_request

            agent = await get_agent_for_request(request)
            channels = agent.config.channels
            if channels is not None:
                wechat_cfg = getattr(channels, "wechat", None)
                if wechat_cfg is not None:
                    return (
                        getattr(wechat_cfg, "base_url", "")
                        or _DEFAULT_BASE_URL
                    )
        except Exception:
            pass
        return _DEFAULT_BASE_URL

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import httpx
        from ..channels.wechat.client import ILinkClient

        base_url = await self._get_base_url(request)
        client = ILinkClient(base_url=base_url)
        await client.start()
        try:
            qr_data = await client.get_bot_qrcode()
        except (httpx.HTTPError, Exception) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"WeChat QR code fetch failed: {exc}",
            ) from exc
        finally:
            await client.stop()

        qrcode = qr_data.get("qrcode", "")
        qrcode_img_content = qr_data.get("qrcode_img_content", "")

        if not qrcode and not qrcode_img_content:
            raise HTTPException(
                status_code=502,
                detail="WeChat returned empty QR code data",
            )

        if qrcode_img_content.startswith("http"):
            scan_url = qrcode_img_content
        else:
            scan_url = (
                f"https://liteapp.weixin.qq.com/q/7GiQu1"
                f"?qrcode={qrcode}&bot_type=3"
            )

        return QRCodeResult(scan_url=scan_url, poll_token=qrcode)

    async def poll_status(self, token: str, request: Request) -> PollResult:
        import httpx
        from ..channels.wechat.client import ILinkClient

        base_url = await self._get_base_url(request)
        client = ILinkClient(base_url=base_url)
        await client.start()
        try:
            data = await client.get_qrcode_status(token)
        except (httpx.HTTPError, Exception) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"WeChat status check failed: {exc}",
            ) from exc
        finally:
            await client.stop()

        return PollResult(
            status=data.get("status", "waiting"),
            credentials={
                "bot_token": data.get("bot_token", ""),
                "base_url": data.get("baseurl", ""),
            },
        )


# ---------------------------------------------------------------------------
# WeCom (Enterprise WeChat) handler
# ---------------------------------------------------------------------------

_WECOM_AUTH_ORIGIN = "https://work.weixin.qq.com"
_WECOM_SOURCE = PROJECT_NAME.lower()


class WecomQRCodeAuthHandler(QRCodeAuthHandler):
    """QR code auth handler for WeCom bot authorization."""

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import json
        import re
        import secrets
        import time
        import httpx

        state = secrets.token_urlsafe(16)
        gen_url = (
            f"{_WECOM_AUTH_ORIGIN}/ai/qc/gen"
            f"?source={_WECOM_SOURCE}&state={state}"
            f"&timestamp={int(time.time() * 1000)}"
        )

        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
            ) as client:
                resp = await client.get(gen_url)
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"WeCom auth page fetch failed: {exc}",
            ) from exc

        settings_match = re.search(
            r"window\.settings\s*=\s*(\{.*\})",
            html,
            re.DOTALL,
        )
        if not settings_match:
            raise HTTPException(
                status_code=502,
                detail="Failed to parse WeCom auth page settings",
            )

        try:
            settings = json.loads(settings_match.group(1))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to parse WeCom settings JSON: {exc}",
            ) from exc

        scode = settings.get("scode", "")
        auth_url = settings.get("auth_url", "")

        if not scode or not auth_url:
            raise HTTPException(
                status_code=502,
                detail="WeCom returned empty scode or auth_url",
            )

        return QRCodeResult(scan_url=auth_url, poll_token=scode)

    async def poll_status(self, token: str, request: Request) -> PollResult:
        from urllib.parse import quote
        import httpx

        query_url = (
            f"{_WECOM_AUTH_ORIGIN}/ai/qc/query_result" f"?scode={quote(token)}"
        )

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(query_url)
                resp.raise_for_status()
                result = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"WeCom status check failed: {exc}",
            ) from exc

        data = result.get("data", {})
        bot_info = data.get("bot_info", {})

        return PollResult(
            status=data.get("status", "waiting"),
            credentials={
                "bot_id": bot_info.get("botid", ""),
                "secret": bot_info.get("secret", ""),
            },
        )


# ---------------------------------------------------------------------------
# DingTalk (Device Flow) handler
# ---------------------------------------------------------------------------

_DINGTALK_API_BASE = "https://oapi.dingtalk.com"
_DINGTALK_SOURCE = "QWENPAW"


class DingtalkQRCodeAuthHandler(QRCodeAuthHandler):
    """QR code auth handler for DingTalk bot registration via Device Flow.

    Flow:
    1. POST /app/registration/init   → nonce (5 min TTL)
    2. POST /app/registration/begin  → device_code + verification_uri_complete
    3. POST /app/registration/poll   → client_id + client_secret on SUCCESS
    """

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Step 1: init – obtain a one-time nonce
                init_resp = await client.post(
                    f"{_DINGTALK_API_BASE}/app/registration/init",
                    json={"source": _DINGTALK_SOURCE},
                )
                init_resp.raise_for_status()
                init_data = init_resp.json()

                if init_data.get("errcode", -1) != 0:
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            f"DingTalk init failed: "
                            f"{init_data.get('errmsg', 'unknown error')}"
                        ),
                    )

                nonce = init_data.get("nonce", "")
                if not nonce:
                    raise HTTPException(
                        status_code=502,
                        detail="DingTalk returned empty nonce",
                    )

                # Step 2: begin – exchange nonce for device_code & QR URL
                begin_resp = await client.post(
                    f"{_DINGTALK_API_BASE}/app/registration/begin",
                    json={"nonce": nonce},
                )
                begin_resp.raise_for_status()
                begin_data = begin_resp.json()

                if begin_data.get("errcode", -1) != 0:
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            f"DingTalk begin failed: "
                            f"{begin_data.get('errmsg', 'unknown error')}"
                        ),
                    )

                device_code = begin_data.get("device_code", "")
                scan_url = begin_data.get("verification_uri_complete", "")

                if not device_code or not scan_url:
                    raise HTTPException(
                        status_code=502,
                        detail="DingTalk returned empty device_code or URI",
                    )

                return QRCodeResult(
                    scan_url=scan_url,
                    poll_token=device_code,
                )

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"DingTalk QR code fetch failed: {exc}",
            ) from exc

    async def poll_status(self, token: str, request: Request) -> PollResult:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_DINGTALK_API_BASE}/app/registration/poll",
                    json={"device_code": token},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"DingTalk status check failed: {exc}",
            ) from exc

        status = data.get("status", "WAITING")

        if status == "SUCCESS":
            return PollResult(
                status="success",
                credentials={
                    "client_id": data.get("client_id", ""),
                    "client_secret": data.get("client_secret", ""),
                },
            )
        elif status == "FAIL":
            return PollResult(
                status="fail",
                credentials={
                    "fail_reason": data.get("fail_reason", ""),
                },
            )
        elif status == "EXPIRED":
            return PollResult(status="expired", credentials={})
        else:
            # WAITING or any other status
            return PollResult(status="waiting", credentials={})


# ---------------------------------------------------------------------------
# Feishu/Lark (Device Authorization Grant - RFC 8628) handler
# ---------------------------------------------------------------------------

_FEISHU_ACCOUNTS_DOMAIN = "https://accounts.feishu.cn"
_LARK_ACCOUNTS_DOMAIN = "https://accounts.larksuite.com"
_FEISHU_REGISTER_ENDPOINT = "/oauth/v1/app/registration"


class FeishuQRCodeAuthHandler(QRCodeAuthHandler):
    """QR code auth handler for Feishu/Lark bot registration via Device Flow.

    Uses the OAuth 2.0 Device Authorization Grant (RFC 8628) protocol
    to enable one-click app creation by scanning a QR code.

    Flow (stateless, similar to DingTalk):
    1. POST action=init   → get supported auth methods
    2. POST action=begin  → device_code + verification_uri_complete
    3. POST action=poll   → client_id + client_secret on SUCCESS
    """

    async def _get_domain(self, request: Request) -> str:
        """Determine if using Feishu (China) or Lark (International) domain.

        Prefers the ``domain`` query parameter (passed by the frontend at QR
        code time) over the saved agent config, because the config may not have
        been persisted yet when the user clicks "获取飞书二维码".
        """
        # 1. Check query parameter first
        qp_domain = request.query_params.get("domain", "")
        if qp_domain in ("feishu", "lark"):
            return qp_domain

        # 2. Fallback to saved agent config
        try:
            from ..agent_context import get_agent_for_request

            agent = await get_agent_for_request(request)
            channels = agent.config.channels
            if channels is not None:
                feishu_cfg = getattr(channels, "feishu", None)
                if feishu_cfg is not None:
                    domain = getattr(feishu_cfg, "domain", "feishu")
                    return domain if domain in ("feishu", "lark") else "feishu"
        except Exception:
            pass
        return "feishu"

    def _get_accounts_domain(self, domain: str) -> str:
        """Get accounts domain based on feishu/lark selection."""
        return (
            _LARK_ACCOUNTS_DOMAIN
            if domain == "lark"
            else _FEISHU_ACCOUNTS_DOMAIN
        )

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        """Initiate device authorization flow and return QR code."""
        import httpx
        from urllib.parse import urlencode

        domain = await self._get_domain(request)
        base_url = self._get_accounts_domain(domain)
        endpoint = base_url + _FEISHU_REGISTER_ENDPOINT

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Step 1: init - get supported auth methods
                init_resp = await client.post(
                    endpoint,
                    content=urlencode({"action": "init"}),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                init_resp.raise_for_status()
                init_data = init_resp.json()

                methods = init_data.get("supported_auth_methods", [])
                if "client_secret" not in methods:
                    raise HTTPException(
                        status_code=502,
                        detail="Feishu: unsupported auth methods",
                    )

                # Step 2: begin - get device_code and QR URL
                begin_resp = await client.post(
                    endpoint,
                    content=urlencode(
                        {
                            "action": "begin",
                            "archetype": "PersonalAgent",
                            "auth_method": "client_secret",
                            "request_user_info": "open_id",
                        },
                    ),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                begin_resp.raise_for_status()
                begin_data = begin_resp.json()

                device_code = begin_data.get("device_code", "")
                verification_uri = begin_data.get(
                    "verification_uri_complete",
                    "",
                )

                if not device_code or not verification_uri:
                    raise HTTPException(
                        status_code=502,
                        detail="Feishu: missing device_code or QR URL",
                    )

                # Build the final QR code URL with source parameter
                if "?" in verification_uri:
                    scan_url = f"{verification_uri}&source={PROJECT_NAME}"
                else:
                    scan_url = f"{verification_uri}?source={PROJECT_NAME}"

                return QRCodeResult(
                    scan_url=scan_url,
                    poll_token=device_code,
                )

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Feishu QR code fetch failed: {exc}",
            ) from exc

    async def poll_status(self, token: str, request: Request) -> PollResult:
        """Poll authorization status using device_code."""
        import httpx
        from urllib.parse import urlencode

        domain = await self._get_domain(request)
        base_url = self._get_accounts_domain(domain)
        endpoint = base_url + _FEISHU_REGISTER_ENDPOINT

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    endpoint,
                    content=urlencode(
                        {
                            "action": "poll",
                            "device_code": token,
                        },
                    ),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                data = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Feishu status check failed: {exc}",
            ) from exc

        # Check for success
        if data.get("client_id") and data.get("client_secret"):
            user_info = data.get("user_info", {})
            return PollResult(
                status="success",
                credentials={
                    "app_id": data["client_id"],
                    "app_secret": data["client_secret"],
                    "open_id": user_info.get("open_id", ""),
                    "tenant_brand": user_info.get("tenant_brand", "feishu"),
                },
            )

        # Check for OAuth errors
        error = data.get("error", "")
        if error in ("expired_token", "invalid_grant"):
            return PollResult(
                status="expired",
                credentials={"fail_reason": "QR code expired"},
            )
        elif error == "access_denied":
            return PollResult(
                status="fail",
                credentials={"fail_reason": "User denied authorization"},
            )
        elif error and error not in ("authorization_pending", "slow_down"):
            return PollResult(
                status="fail",
                credentials={"fail_reason": error},
            )

        # Default: waiting (authorization_pending, slow_down, or no error)
        return PollResult(status="waiting", credentials={})


# ---------------------------------------------------------------------------
# Cryptographic helpers
# ---------------------------------------------------------------------------

_AES_KEY_LENGTH = 32  # 256 bits


def _generate_bind_key() -> str:
    """Return a base64-encoded 256-bit AES key."""
    return base64.b64encode(os.urandom(_AES_KEY_LENGTH)).decode()


def _decrypt_secret(
    encrypted_base64: str,
    key_base64: str,
    associated_data: bytes | None = None,
) -> str:
    """Decrypt an AES-256-GCM ciphertext (base64)."""
    key = base64.b64decode(key_base64)
    raw = base64.b64decode(encrypted_base64)

    if len(raw) < 28:  # 12-byte IV + at least 16 bytes (ciphertext+tag)
        raise ValueError(f"Ciphertext too short: {len(raw)} bytes (min 28)")

    iv = raw[:12]
    ciphertext_with_tag = raw[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext_with_tag, associated_data)
    return plaintext.decode("utf-8")


def _encode_poll_token(task_id: str, aes_key: str) -> str:
    """Combine task_id and AES key into a stateless token."""
    import json

    payload = json.dumps(
        {"task_id": task_id, "key": aes_key},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_poll_token(token: str) -> Tuple[str, str]:
    """Decode token back to (task_id, aes_key)."""
    import json

    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        data = json.loads(decoded)
        return data["task_id"], data["key"]
    except Exception as exc:
        raise ValueError(f"Invalid poll token: {exc}") from exc


# ---------------------------------------------------------------------------
# QQ QR code handler
# ---------------------------------------------------------------------------


class QQQRCodeAuthHandler(QRCodeAuthHandler):
    """QR code auth handler for QQ bot authorization via Portal bind task."""

    _PORTAL_HOST: str = os.getenv("QQ_PORTAL_HOST", "q.qq.com")
    _CREATE_PATH: str = "/lite/create_bind_task"
    _POLL_PATH: str = "/lite/poll_bind_result"
    _FRONTEND_PATH: str = "/qqbot/openclaw/connect.html"

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import httpx
        from urllib.parse import urlencode

        aes_key = _generate_bind_key()
        url = f"https://{self._PORTAL_HOST}{self._CREATE_PATH}"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    json={"key": aes_key},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"QQ create_bind_task failed: {exc}",
            ) from exc

        if data.get("retcode") != 0:
            raise HTTPException(
                status_code=502,
                detail=f"QQ create_bind_task error: {data.get('msg', '')}",
            )

        task_id = data.get("data", {}).get("task_id")
        if not task_id:
            raise HTTPException(
                status_code=502,
                detail="QQ create_bind_task returned empty task_id",
            )

        params = urlencode(
            {"task_id": task_id, "_wv": "2", "source": PROJECT_NAME},
        )
        scan_url = f"https://{self._PORTAL_HOST}{self._FRONTEND_PATH}?{params}"
        poll_token = _encode_poll_token(task_id, aes_key)
        return QRCodeResult(scan_url=scan_url, poll_token=poll_token)

    async def poll_status(self, token: str, request: Request) -> PollResult:
        import httpx

        try:
            task_id, aes_key = _decode_poll_token(token)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid poll token",
            ) from exc

        url = f"https://{self._PORTAL_HOST}{self._POLL_PATH}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    json={"task_id": task_id},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"QQ poll_bind_result failed: {exc}",
            ) from exc

        retcode = data.get("retcode")
        if retcode != 0:
            return PollResult(
                status="fail",
                credentials={"fail_reason": data.get("msg", "unknown")},
            )

        result_data = data.get("data", {})
        status = result_data.get("status", -1)

        if status == 2:
            # Completed – decrypt secret
            raw_appid = result_data.get("bot_appid")
            encrypted_secret = result_data.get("bot_encrypt_secret", "")
            if not raw_appid or not encrypted_secret:
                return PollResult(
                    status="fail",
                    credentials={"fail_reason": "Missing app_id or secret"},
                )
            try:
                client_secret = _decrypt_secret(encrypted_secret, aes_key)
            except Exception:
                return PollResult(
                    status="fail",
                    credentials={"fail_reason": "Secret decryption failed"},
                )
            return PollResult(
                status="success",
                credentials={
                    "app_id": str(raw_appid),
                    "client_secret": client_secret,
                    "user_openid": str(result_data.get("user_openid", "")),
                },
            )
        elif status == 3:
            return PollResult(status="expired", credentials={})
        else:
            return PollResult(status="waiting", credentials={})


# ---------------------------------------------------------------------------
# Handler registry – add new channels here
# ---------------------------------------------------------------------------

QRCODE_AUTH_HANDLERS: Dict[str, QRCodeAuthHandler] = {
    "wechat": WeChatQRCodeAuthHandler(),
    "wecom": WecomQRCodeAuthHandler(),
    "dingtalk": DingtalkQRCodeAuthHandler(),
    "feishu": FeishuQRCodeAuthHandler(),
    "qq": QQQRCodeAuthHandler(),
}

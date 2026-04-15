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
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

import segno
from fastapi import HTTPException, Request

from ...constant import PROJECT_NAME


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


class WeixinQRCodeAuthHandler(QRCodeAuthHandler):
    """QR code auth handler for WeChat iLink Bot login."""

    async def _get_base_url(self, request: Request) -> str:
        from ..channels.weixin.client import _DEFAULT_BASE_URL

        try:
            from ..agent_context import get_agent_for_request

            agent = await get_agent_for_request(request)
            channels = agent.config.channels
            if channels is not None:
                weixin_cfg = getattr(channels, "weixin", None)
                if weixin_cfg is not None:
                    return (
                        getattr(weixin_cfg, "base_url", "")
                        or _DEFAULT_BASE_URL
                    )
        except Exception:
            pass
        return _DEFAULT_BASE_URL

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import httpx
        from ..channels.weixin.client import ILinkClient

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
        from ..channels.weixin.client import ILinkClient

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
# Handler registry – add new channels here
# ---------------------------------------------------------------------------

QRCODE_AUTH_HANDLERS: Dict[str, QRCodeAuthHandler] = {
    "weixin": WeixinQRCodeAuthHandler(),
    "wecom": WecomQRCodeAuthHandler(),
    "dingtalk": DingtalkQRCodeAuthHandler(),
}

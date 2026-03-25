# -*- coding: utf-8 -*-
"""Wechat QR login APIs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from time import time
from typing import Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...config.config import WechatConfig, save_agent_config
from ..agent_context import get_agent_for_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wechat", tags=["wechat"])

DEFAULT_API_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_BOT_TYPE = "3"
SESSION_TTL_SECONDS = 5 * 60
QR_STATUS_DEFAULT_TIMEOUT_MS = 35_000


@dataclass
class _QrSession:
    """In-memory session for one QR login flow."""

    session_key: str
    qrcode: str
    qrcode_url: str
    base_url: str
    bot_type: str
    created_at: float


_SESSIONS: Dict[str, _QrSession] = {}
_SESSIONS_LOCK = asyncio.Lock()


class WechatQrStartBody(BaseModel):
    """Request body for QR start API."""

    base_url: Optional[str] = Field(
        default=None,
        description="Optional override for Wechat API base URL.",
    )
    bot_type: str = Field(
        default=DEFAULT_BOT_TYPE,
        description="bot_type for get_bot_qrcode.",
    )
    force: bool = Field(
        default=False,
        description="Force refresh QR session.",
    )


class WechatQrStartResponse(BaseModel):
    """Response body for QR start API."""

    session_key: str
    qrcode_url: str
    qrcode_text: str
    message: str
    expires_in_seconds: int = SESSION_TTL_SECONDS


class WechatQrWaitBody(BaseModel):
    """Request body for QR wait API."""

    session_key: str = Field(..., min_length=1)
    timeout_ms: int = Field(
        default=QR_STATUS_DEFAULT_TIMEOUT_MS,
        ge=1000,
        le=120000,
    )


class WechatQrWaitResponse(BaseModel):
    """Response body for QR wait API."""

    connected: bool
    status: str
    message: str
    account_id: str = ""
    user_id: str = ""


def _session_fresh(s: _QrSession) -> bool:
    return (time() - s.created_at) < SESSION_TTL_SECONDS


async def _purge_expired_sessions() -> None:
    """Remove expired QR sessions from memory."""
    async with _SESSIONS_LOCK:
        expired = [k for k, v in _SESSIONS.items() if not _session_fresh(v)]
        for key in expired:
            _SESSIONS.pop(key, None)


def _normalize_base_url(url: str) -> str:
    s = (url or "").strip()
    if not s:
        return DEFAULT_API_BASE_URL
    if s.endswith("/"):
        return s[:-1]
    return s


def _resolve_qrcode_image_url(base_url: str, raw: str) -> str:
    """Normalize upstream QR image field to a displayable image URL."""
    value = (raw or "").strip()
    if not value:
        return ""
    if value.startswith("data:image/"):
        return value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("//"):
        scheme = "https" if base_url.startswith("https://") else "http"
        return f"{scheme}:{value}"
    if value.startswith("/"):
        return f"{base_url}{value}"
    # Upstream may return QR content text instead of direct image URL.
    return ""


async def _fetch_qrcode(base_url: str, bot_type: str) -> dict:
    """Fetch QR code payload from upstream."""
    url = f"{base_url}/ilink/bot/get_bot_qrcode"
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.get(
            url,
            params={"bot_type": bot_type or DEFAULT_BOT_TYPE},
        )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to fetch Wechat QR code: "
                f"{resp.status_code} {resp.text[:200]}"
            ),
        )
    data = resp.json()
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail="Wechat QR response is not a JSON object",
        )
    qrcode = str(data.get("qrcode") or "").strip()
    qrcode_url = str(data.get("qrcode_img_content") or "").strip()
    if not qrcode or not qrcode_url:
        raise HTTPException(
            status_code=502,
            detail="Wechat QR response missing qrcode or qrcode_img_content",
        )
    return {"qrcode": qrcode, "qrcode_url": qrcode_url}


async def _poll_qrcode_status(
    base_url: str,
    qrcode: str,
    timeout_ms: int,
) -> dict:
    """Long-poll QR status from upstream."""
    url = f"{base_url}/ilink/bot/get_qrcode_status"
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_ms / 1000.0),
    ) as client:
        try:
            resp = await client.get(
                url,
                params={"qrcode": qrcode},
                headers={"iLink-App-ClientVersion": "1"},
            )
        except httpx.TimeoutException:
            return {"status": "wait"}
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to poll Wechat QR status: "
                f"{resp.status_code} {resp.text[:200]}"
            ),
        )
    data = resp.json()
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail="Wechat QR status response is not a JSON object",
        )
    status = str(data.get("status") or "").strip()
    if not status:
        raise HTTPException(
            status_code=502,
            detail="Wechat QR status response missing status field",
        )
    return data


@router.post(
    "/login/qr/start",
    response_model=WechatQrStartResponse,
    summary="Start Wechat QR login",
)
async def post_wechat_qr_start(
    request: Request,
    body: WechatQrStartBody,
) -> WechatQrStartResponse:
    """Start Wechat QR flow and return QR data URL."""
    workspace = await get_agent_for_request(request)
    cfg = workspace.config.channels.wechat
    if not isinstance(cfg, WechatConfig):
        cfg = WechatConfig()

    base_url = _normalize_base_url(body.base_url or cfg.base_url)
    bot_type = (body.bot_type or DEFAULT_BOT_TYPE).strip() or DEFAULT_BOT_TYPE

    await _purge_expired_sessions()
    payload = await _fetch_qrcode(base_url=base_url, bot_type=bot_type)
    session_key = uuid.uuid4().hex
    session = _QrSession(
        session_key=session_key,
        qrcode=payload["qrcode"],
        qrcode_url=payload["qrcode_url"],
        base_url=base_url,
        bot_type=bot_type,
        created_at=time(),
    )
    async with _SESSIONS_LOCK:
        _SESSIONS[session_key] = session

    return WechatQrStartResponse(
        session_key=session_key,
        qrcode_url=_resolve_qrcode_image_url(base_url, payload["qrcode_url"]),
        qrcode_text=payload["qrcode_url"],
        message="QR code generated. Please scan with Wechat.",
    )


@router.post(
    "/login/qr/wait",
    response_model=WechatQrWaitResponse,
    summary="Wait Wechat QR login status",
)
async def post_wechat_qr_wait(
    request: Request,
    body: WechatQrWaitBody,
) -> WechatQrWaitResponse:
    """Poll Wechat QR status and persist token on success."""
    workspace = await get_agent_for_request(request)
    await _purge_expired_sessions()

    async with _SESSIONS_LOCK:
        session = _SESSIONS.get(body.session_key)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="QR session not found or expired",
        )
    if not _session_fresh(session):
        async with _SESSIONS_LOCK:
            _SESSIONS.pop(body.session_key, None)
        return WechatQrWaitResponse(
            connected=False,
            status="expired",
            message="QR code expired, please restart login.",
        )

    status_payload = await _poll_qrcode_status(
        base_url=session.base_url,
        qrcode=session.qrcode,
        timeout_ms=body.timeout_ms,
    )
    status = str(status_payload.get("status") or "wait").strip()

    if status != "confirmed":
        if status == "expired":
            async with _SESSIONS_LOCK:
                _SESSIONS.pop(body.session_key, None)
        return WechatQrWaitResponse(
            connected=False,
            status=status,
            message=f"Current QR status: {status}",
        )

    bot_token = str(status_payload.get("bot_token") or "").strip()
    if not bot_token:
        raise HTTPException(
            status_code=502,
            detail="QR confirmed but bot_token is missing",
        )

    account_id = str(status_payload.get("ilink_bot_id") or "").strip()
    user_id = str(status_payload.get("ilink_user_id") or "").strip()
    base_url = _normalize_base_url(
        str(status_payload.get("baseurl") or session.base_url),
    )

    cfg = workspace.config.channels.wechat
    if not isinstance(cfg, WechatConfig):
        cfg = WechatConfig()
    cfg.enabled = True
    cfg.base_url = base_url
    cfg.bot_token = bot_token
    # Keep a stable UIN so channel requests use a consistent identity header.
    if user_id:
        cfg.uin = user_id
    elif account_id and not cfg.uin:
        cfg.uin = account_id
    workspace.config.channels.wechat = cfg
    save_agent_config(workspace.agent_id, workspace.config)

    manager = request.app.state.multi_agent_manager
    agent_id = workspace.agent_id

    async def _reload_in_background() -> None:
        try:
            await manager.reload_agent(agent_id)
        except Exception as exc:
            logger.warning("wechat qr login reload failed: %s", exc)

    asyncio.create_task(_reload_in_background())
    async with _SESSIONS_LOCK:
        _SESSIONS.pop(body.session_key, None)

    return WechatQrWaitResponse(
        connected=True,
        status="confirmed",
        message="Wechat login confirmed and token saved.",
        account_id=account_id,
        user_id=user_id,
    )

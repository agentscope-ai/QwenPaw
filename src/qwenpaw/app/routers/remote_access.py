# -*- coding: utf-8 -*-
"""Local Console endpoints for secure Platform Relay enrollment."""
from __future__ import annotations

import json
import time
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ...constant import EnvVarLoader, SECRET_DIR
from ...remote_access import (
    RelayLocalApi,
    RelayNodeConnectionService,
    RelayNodeSupervisor,
    RelayNodeTransport,
    RelayPlatformError,
)
from ...remote_access.enrollment import RelayEnrollmentService
from ...remote_access.store import RelayNodeStore
from ..channels.qrcode_auth_handler import generate_qrcode_image


router = APIRouter(prefix="/remote-access", tags=["remote-access"])
callback_router = APIRouter(tags=["remote-access"])

_PLATFORM_URL = EnvVarLoader.get_str(
    "QWENPAW_PLATFORM_URL",
    "https://platform.agentscope.io",
)
_store = RelayNodeStore(SECRET_DIR / "relay-node.json")
_service = RelayEnrollmentService(_store)
_connection_service = RelayNodeConnectionService(
    _store,
    RelayNodeTransport(RelayLocalApi().dispatcher()),
)
_supervisor = RelayNodeSupervisor(
    _connection_service,
)


class RelayAuthorizationRequest(BaseModel):
    """Start a Platform authorization for this local QwenPaw."""

    platform_url: str = Field(default=_PLATFORM_URL, max_length=2048)
    name: str = Field(min_length=1, max_length=128)


@router.get("/platform", summary="Get Platform Relay connection state")
async def platform_relay_status() -> dict:
    """Return only non-secret Relay connection metadata."""
    status = await _service.status()
    if status.status == "connected":
        _supervisor.start()
    return {
        **asdict(status),
        "transport_status": _supervisor.status,
        "transport_error": _supervisor.last_error,
    }


@router.post(
    "/platform/authorize",
    summary="Authorize this QwenPaw with Platform",
)
async def authorize_platform(
    body: RelayAuthorizationRequest,
    request: Request,
) -> dict:
    """Start Node PKCE OAuth; LAN direct pairing is unaffected."""
    try:
        status = await _service.start(
            platform_url=body.platform_url,
            name=body.name.strip(),
            callback_port=request.url.port or 8088,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RelayPlatformError as exc:
        raise _platform_http_error(exc) from exc
    return asdict(status)


@callback_router.get("/callback/{nonce}", response_class=HTMLResponse)
async def complete_platform_authorization(
    nonce: str,
    state: str,
    code: str,
) -> HTMLResponse:
    """Complete the localhost PKCE callback and register the Node."""
    try:
        await _service.complete_oauth(
            nonce=nonce,
            state_value=state,
            code=code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RelayPlatformError as exc:
        raise _platform_http_error(exc) from exc
    _supervisor.start()
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<title>QwenPaw connected</title>"
        "<style>body{font:16px system-ui;margin:48px;line-height:1.6}"
        "h1{color:#ff6a00}</style>"
        "<h1>QwenPaw 已连接</h1>"
        "<p>可以关闭此页面并返回 QwenPaw。</p>"
    )


@router.post(
    "/platform/pairing",
    summary="Create a one-time Mobile Relay pairing code",
)
async def create_platform_relay_pairing() -> dict:
    """Return the exact JSON payload encoded by the local QR renderer."""
    try:
        status = await _service.status()
        if status.platform_url is None:
            raise ValueError("QwenPaw is not registered with Platform Relay")
        ticket = await _connection_service.create_pairing_ticket()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RelayPlatformError as exc:
        raise _platform_http_error(exc) from exc
    payload = {
        "type": "qwenpaw.relay.pairing",
        "v": 2,
        "issuer": status.platform_url,
        "node_id": ticket.node_id,
        "qwenpaw_id": ticket.qwenpaw_id,
        "pairing_ticket": ticket.token,
        "node_public_key_thumbprint": (ticket.node_public_key_thumbprint),
        "dpop_nonce": ticket.dpop_nonce,
        "protocol_version": 1,
        "expires_in": ticket.expires_in,
    }
    qr_payload = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        **payload,
        "qr_payload": qr_payload,
        "qrcode_img": generate_qrcode_image(qr_payload),
        "expires_at": int(time.time()) + ticket.expires_in,
    }


def _platform_http_error(exc: RelayPlatformError) -> HTTPException:
    status_code = exc.status_code
    if exc.code in {"authorization_pending", "slow_down"}:
        status_code = 409
    return HTTPException(
        status_code=status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "retryable": exc.retryable,
        },
    )

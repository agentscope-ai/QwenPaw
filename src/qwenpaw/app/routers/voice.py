# -*- coding: utf-8 -*-
"""Stable public voice paths delegated to host-owned generic ingress."""

from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, Response, WebSocket

from ..channels.ingress import route_is_unowned

voice_router = APIRouter(tags=["voice"])


def _legacy_unowned(request, service):
    try:
        query = parse_qsl(
            request.scope.get("query_string", b"").decode("ascii"),
            keep_blank_values=True,
            max_num_fields=4096,
        )
    except (ValueError, UnicodeError):
        return False
    if any(key == "_qp_endpoint" for key, _ in query):
        return False
    state = request.app.state
    registry = getattr(state, "plugin_registry", None)
    if registry is None:
        registry = getattr(
            getattr(state, "plugin_loader", None),
            "registry",
            None,
        )
    return route_is_unowned(
        registry,
        request.method,
        request.scope["path"],
        service=service,
    )


@voice_router.post("/voice/incoming")
async def voice_incoming(request: Request) -> Response:
    service = getattr(request.app.state, "channel_ingress", None)
    if _legacy_unowned(request, service):
        return Response(
            content=(
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response><Say>Voice channel is not available.</Say></Response>"
            ),
            media_type="application/xml",
        )
    if service is None:
        return Response(status_code=503)
    return await service.forward_http(request)


@voice_router.websocket("/voice/ws")
async def voice_ws(websocket: WebSocket) -> None:
    service = getattr(websocket.app.state, "channel_ingress", None)
    if service is None:
        await websocket.close(code=1013, reason="Channel ingress unavailable")
        return
    await service.forward_websocket(websocket)


@voice_router.post("/voice/status-callback")
async def voice_status_callback(request: Request) -> Response:
    service = getattr(request.app.state, "channel_ingress", None)
    if _legacy_unowned(request, service):
        return Response(status_code=204)
    if service is None:
        return Response(status_code=503)
    return await service.forward_http(request)

# -*- coding: utf-8 -*-
"""Exact host-approved channel callbacks; each platform authenticates its input."""

from fastapi import APIRouter, Request, Response, WebSocket

channel_callbacks_router = APIRouter(tags=["channel-callbacks"])


@channel_callbacks_router.api_route(
    "/channel-callbacks/{namespace}/{channel_key}/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def callback_http(request: Request) -> Response:
    service = getattr(request.app.state, "channel_ingress", None)
    if service is None:
        return Response(status_code=503)
    return await service.forward_http(request)


@channel_callbacks_router.websocket(
    "/channel-callbacks/{namespace}/{channel_key}/{path:path}",
)
async def callback_websocket(websocket: WebSocket) -> None:
    service = getattr(websocket.app.state, "channel_ingress", None)
    if service is None:
        await websocket.close(code=1013, reason="Channel ingress unavailable")
        return
    await service.forward_websocket(websocket)

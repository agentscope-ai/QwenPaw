# -*- coding: utf-8 -*-
"""WeCom callback router.

Endpoints are mounted at app root level:
- GET/POST /wecom
- GET/POST /wecom-app
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response

wecom_router = APIRouter(tags=["wecom"])


def _get_channel(request: Request, channel_key: str):
    app = getattr(request, "app", None)
    if app is None:
        return None
    cm = getattr(app.state, "channel_manager", None)
    if cm is None:
        return None
    for ch in cm.channels:
        if ch.channel == channel_key:
            return ch
    return None


async def _dispatch(
    request: Request,
    *,
    channel_key: str,
) -> Response:
    ch = _get_channel(request, channel_key)
    if ch is None:
        return Response(
            content=f"{channel_key} channel not available",
            status_code=503,
            media_type="text/plain",
        )

    body_text = ""
    if request.method.upper() == "POST":
        body_text = (await request.body()).decode("utf-8", errors="replace")

    status, content_type, body = await ch.handle_callback(
        method=request.method,
        request_url=str(request.url),
        body_text=body_text,
    )
    return Response(
        content=body,
        status_code=status,
        media_type=content_type,
    )


@wecom_router.api_route("/wecom", methods=["GET", "POST"])
async def wecom_callback(request: Request) -> Response:
    return await _dispatch(request, channel_key="wecom")


@wecom_router.api_route("/wecom-app", methods=["GET", "POST"])
async def wecom_app_callback(request: Request) -> Response:
    return await _dispatch(request, channel_key="wecom_app")

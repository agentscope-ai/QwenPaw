# -*- coding: utf-8 -*-
"""WeCom callback router.

Endpoints are mounted at app root level:
- GET/POST /wecom
- GET/POST /wecom-app
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.routing import APIRoute

wecom_router = APIRouter(tags=["wecom"])
_DEFAULT_WEBHOOK_PATHS = {
    "wecom": "/wecom",
    "wecom_app": "/wecom-app",
}


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


def _normalize_webhook_path(path: str | None, default: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return default
    normalized = raw if raw.startswith("/") else f"/{raw}"
    return normalized.rstrip("/") or default


def sync_wecom_callback_routes(app: FastAPI, channel_manager) -> None:
    """Register alias callback routes for configured webhook paths.

    Default routes stay mounted via ``wecom_router``.
    Non-default paths are added dynamically so ``webhook_path`` in config,
    CLI, and Console matches actual HTTP routing behavior.
    """
    old_paths = set(
        getattr(app.state, "wecom_dynamic_route_paths", set()) or set(),
    )
    if old_paths:
        app.router.routes = [
            route
            for route in app.router.routes
            if not (
                isinstance(route, APIRoute)
                and route.path in old_paths
                and str(route.name or "").startswith("wecom_dynamic_")
            )
        ]

    new_paths: set[str] = set()
    for ch in getattr(channel_manager, "channels", []):
        channel_key = getattr(ch, "channel", "")
        default_path = _DEFAULT_WEBHOOK_PATHS.get(channel_key)
        if not default_path:
            continue
        alias_path = _normalize_webhook_path(
            getattr(ch, "webhook_path", ""),
            default_path,
        )
        if alias_path == default_path:
            continue

        async def _alias_handler(
            request: Request,
            *,
            _channel_key: str = channel_key,
        ) -> Response:
            return await _dispatch(request, channel_key=_channel_key)

        route_name = (
            f"wecom_dynamic_{channel_key}_"
            f"{alias_path.strip('/').replace('/', '_') or 'root'}"
        )
        app.add_api_route(
            alias_path,
            _alias_handler,
            methods=["GET", "POST"],
            tags=["wecom"],
            name=route_name,
        )
        new_paths.add(alias_path)

    app.state.wecom_dynamic_route_paths = new_paths


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

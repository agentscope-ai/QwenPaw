# -*- coding: utf-8 -*-
"""get_ctx — FastAPI dependency that creates PawAppContext per request.

Usage in Router mode:
    from qwenpaw.pawapp import get_ctx
    from fastapi import Depends

    @router.get("/projects")
    async def list_projects(ctx=Depends(get_ctx)):
        return await ctx.storage.get("projects", default=[])

The dependency extracts ``app_id`` from the request path and constructs
a PawAppContext wired to the running services (workspace_registry,
app_services, plugin_registry, session).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException, Request

from .context import PawAppContext

logger = logging.getLogger(__name__)

#: Channel recorded for requests arriving through the standard PawApp
#: capability routes. Those routes are only reachable from app frontends
#: hosted by the console, so the channel is pinned rather than trusted
#: from the request.
_SCOPED_CHANNEL = "console"


def _extract_app_id_from_request(request: Request) -> str:
    """Extract PawApp ID from the request.

    Priority:
    1. request.state.app_id (explicit injection by router)
    2. X-PawApp-Id header
    3. URL path parsing for /api/{app_id}/... pattern
    """
    # Priority 1: explicit injection (most reliable)
    if hasattr(request.state, "app_id") and request.state.app_id:
        return request.state.app_id

    # Priority 2: header (for iframe/cross-origin scenarios)
    app_id = request.headers.get("X-PawApp-Id", "")
    if app_id:
        return app_id

    # Priority 3: parse URL path /api/{app_id}/...
    # Real PawApp routes registered by PawApp.register() are /api/{app_id}/...
    parts = request.url.path.split("/")
    if len(parts) >= 3 and parts[1] == "api" and parts[2]:
        return parts[2]

    return "unknown"


def _get_session(request: Request) -> Any:
    """Get or create a SafeJSONSession for PawApp storage."""
    # pylint: disable=unused-argument
    try:
        from ..app.chats.session import SafeJSONSession
        from ..constant import WORKING_DIR

        return SafeJSONSession(save_dir=str(WORKING_DIR))
    except Exception:
        return None


def _build_ctx(
    request: Request,
    *,
    user_id: str,
    channel: str,
) -> PawAppContext:
    """Construct a PawAppContext wired to the running host services."""
    app_id = _extract_app_id_from_request(request)

    # Read services from app state (set by lifespan)
    app_state = request.app.state
    workspace_registry = getattr(app_state, "multi_agent_manager", None)
    app_services = getattr(app_state, "app_services", None)
    plugin_registry = getattr(app_state, "plugin_registry", None)

    # Get or create session for storage
    session = _get_session(request)

    agent_id = request.query_params.get("agent_id", "default")

    return PawAppContext(
        app_id=app_id,
        agent_id=agent_id,
        channel=channel,
        user_id=user_id,
        _workspace_registry=workspace_registry,
        _app_services=app_services,
        _plugin_registry=plugin_registry,
        _session=session,
        _sse_channel=None,  # Set by TaskManager for long-running tasks
    )


async def get_ctx(request: Request) -> PawAppContext:
    """FastAPI dependency that provides PawAppContext.

    Injects all available services from ``request.app.state``.
    Extracts agent_id, channel, and user_id from request. Kept for
    additive compatibility with legacy PawApp routes; new standard
    capability routes use :func:`get_scoped_ctx` instead, which binds
    identity to the authenticated principal.
    """
    channel = (
        request.query_params.get("channel")
        or request.headers.get("X-Channel")
        or "console"
    )
    user_id = (
        request.query_params.get("user_id")
        or request.headers.get("X-User-Id")
        or "default"
    )
    return _build_ctx(request, user_id=user_id, channel=channel)


def _claimed_identity(request: Request) -> tuple[Optional[str], Optional[str]]:
    """Return the caller-supplied (user_id, channel) claims, if any."""
    user_claim = request.query_params.get("user_id") or request.headers.get(
        "X-User-Id",
    )
    channel_claim = request.query_params.get(
        "channel",
    ) or request.headers.get("X-Channel")
    return user_claim or None, channel_claim or None


async def get_scoped_ctx(request: Request) -> PawAppContext:
    """Strict variant of :func:`get_ctx` for standard capability routes.

    ``user_id`` is bound to the authenticated principal established by
    ``AuthMiddleware`` (``request.state.user``) and ``channel`` is pinned
    to the console. Caller-supplied identity claims are rejected when they
    disagree with the bound scope instead of being silently trusted, so a
    request can never read or write another user's or channel's data
    through the standard routes.
    """
    principal = getattr(request.state, "user", None)
    user_id = str(principal) if principal else "default"

    user_claim, channel_claim = _claimed_identity(request)
    if user_claim is not None and user_claim != user_id:
        raise HTTPException(
            status_code=403,
            detail="user_id does not match the authenticated user",
        )
    if channel_claim is not None and channel_claim != _SCOPED_CHANNEL:
        raise HTTPException(
            status_code=403,
            detail="channel is not available on app routes",
        )

    return _build_ctx(request, user_id=user_id, channel=_SCOPED_CHANNEL)

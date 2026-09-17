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
from typing import Any

from fastapi import HTTPException, Request

from ..access.dependencies import get_actor
from ..identity.runtime import get_identity_schema, is_multi_user_enabled
from ..plugins.governance import (
    PluginAccessError,
    PluginGovernanceService,
    PostgresPluginGovernanceRepository,
)
from .context import PawAppContext

logger = logging.getLogger(__name__)


def _plugin_governance_service() -> PluginGovernanceService:
    return PluginGovernanceService(
        PostgresPluginGovernanceRepository(schema=get_identity_schema())
    )


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
    except Exception:  # noqa: BLE001 - SDK 依赖不可用时保持原降级语义
        return None


async def get_ctx(request: Request) -> PawAppContext:
    """FastAPI dependency that provides PawAppContext.

    Injects all available services from ``request.app.state``.
    Extracts agent_id, channel, and user_id from request.
    """
    app_id = _extract_app_id_from_request(request)

    # Read services from app state (set by lifespan)
    app_state = request.app.state
    workspace_registry = getattr(app_state, "multi_agent_manager", None)
    app_services = getattr(app_state, "app_services", None)
    plugin_registry = getattr(app_state, "plugin_registry", None)

    # Get or create session for storage
    session = _get_session(request)

    # 多用户身份只来自认证中间件和已校验的 Agent 上下文。
    if is_multi_user_enabled():
        actor = get_actor(request)
        try:
            await _plugin_governance_service().require_app_access(actor, app_id)
        except PluginAccessError as exc:
            raise HTTPException(status_code=404, detail="pawapp_not_found") from exc
        user_id = str(actor.user_id)
        agent_access = getattr(request.state, "agent_access", None)
        agent_id = getattr(agent_access, "agent_key", None) or "default"
    else:
        agent_id = request.query_params.get("agent_id", "default")
        user_id = (
            request.query_params.get("user_id")
            or request.headers.get("X-User-Id")
            or "default"
        )
    channel = (
        request.query_params.get("channel")
        or request.headers.get("X-Channel")
        or "console"
    )

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

# -*- coding: utf-8 -*-
"""Agent-scoped router that wraps existing routers under /agents/{agentId}/

This provides agent isolation by injecting agentId into request.state,
allowing downstream APIs to access the correct agent context.
"""
from fastapi import APIRouter, Request
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import Response


class AgentContextMiddleware(BaseHTTPMiddleware):
    """Middleware to inject agentId into request.state."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Extract agentId and root_session_id from path/headers."""
        import logging
        from ..agent_context import set_current_agent_id

        logger = logging.getLogger(__name__)
        agent_id = None

        # Priority 1: Extract agentId from path: /api/agents/{agentId}/...
        path_parts = request.url.path.split("/")
        if len(path_parts) >= 4 and path_parts[1] == "api":
            if path_parts[2] == "agents":
                agent_id = path_parts[3]
                request.state.agent_id = agent_id
                logger.debug(
                    f"AgentContextMiddleware: agent_id={agent_id} "
                    f"from path={request.url.path}",
                )

        # Priority 2: Check X-Agent-Id header
        if not agent_id:
            agent_id = request.headers.get("X-Agent-Id")

        # Set agent_id in context variable for use by runners
        if agent_id:
            set_current_agent_id(agent_id)

        # Extract X-Root-Session-Id header for cross-session approval routing
        root_session_id = request.headers.get("X-Root-Session-Id")
        if root_session_id:
            # Inject into request.request_context for runner access
            if not hasattr(request, "request_context"):
                request.request_context = {}
            request.request_context["root_session_id"] = root_session_id
            logger.debug(
                "AgentContextMiddleware: root_session_id=%s from "
                "X-Root-Session-Id header",
                root_session_id[:12],
            )

        response = await call_next(request)
        return response


def create_agent_scoped_router() -> APIRouter:
    """Create router that wraps all existing routers under /{agentId}/

    Returns:
        APIRouter with all sub-routers mounted under /{agentId}/
    """
    from .skills import router as skills_router
    from .tools import router as tools_router
    from .config import router as config_router
    from .mcp import router as mcp_router
    from .workspace import router as workspace_router
    from ..crons.api import router as cron_router
    from ..runner.api import router as chats_router
    from .console import router as console_router
    from .plugins import router as plugins_router
    from .plan import router as plan_router
    from .progress_observing import router as progress_observing_router

    router = APIRouter(prefix="/agents/{agentId}", tags=["agent-scoped"])

    # Include all agent-specific sub-routers (they keep their own prefixes)
    # /agents/{agentId}/chats/* -> chats_router
    # /agents/{agentId}/config/* -> config_router (channels, heartbeat)
    # /agents/{agentId}/cron/* -> cron_router
    # /agents/{agentId}/mcp/* -> mcp_router
    # /agents/{agentId}/skills/* -> skills_router
    # /agents/{agentId}/tools/* -> tools_router
    # /agents/{agentId}/workspace/* -> workspace_router
    router.include_router(chats_router)
    router.include_router(config_router)
    router.include_router(cron_router)
    router.include_router(mcp_router)
    router.include_router(skills_router)
    router.include_router(tools_router)
    router.include_router(workspace_router)
    router.include_router(console_router)
    router.include_router(plugins_router)
    router.include_router(plan_router)
    router.include_router(progress_observing_router)

    return router

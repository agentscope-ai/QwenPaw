# -*- coding: utf-8 -*-
"""Agent-scoped router that wraps existing routers under /agents/{agentId}/

This provides agent isolation by injecting agentId into request.state,
allowing downstream APIs to access the correct agent context.
"""

from fastapi import APIRouter, Request


class AgentContextMiddleware:
    """Middleware to inject agentId into request.state.

    Implemented as a pure-ASGI middleware (not ``BaseHTTPMiddleware``)
    so that streaming responses (SSE) are forwarded chunk-by-chunk
    without buffering.  ``BaseHTTPMiddleware`` bridges the response
    through an internal anyio memory stream which delays flushes and
    breaks real-time SSE delivery.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        import logging
        from ..agent_context import set_current_agent_id

        logger = logging.getLogger(__name__)
        request = Request(scope, receive)
        agent_id = None

        # Priority 1: Extract agentId from path: /api/agents/{agentId}/...
        path_parts = request.url.path.split("/")
        if len(path_parts) >= 4 and path_parts[1] == "api":
            if path_parts[2] == "agents":
                agent_id = path_parts[3]
                # ``request.state`` is backed by ``scope["state"]``, so
                # this value is visible to downstream code that builds
                # its own ``Request`` from the same scope.
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
            # Store on request.state (not a custom Request attribute)
            # so it survives into downstream code under pure ASGI.
            if not hasattr(request.state, "request_context"):
                request.state.request_context = {}
            request.state.request_context["root_session_id"] = root_session_id
            logger.debug(
                "AgentContextMiddleware: root_session_id=%s from "
                "X-Root-Session-Id header",
                root_session_id[:12],
            )

        return await self.app(scope, receive, send)


def create_agent_scoped_router() -> APIRouter:
    """Create router that wraps all existing routers under /{agentId}/

    Returns:
        APIRouter with all sub-routers mounted under /{agentId}/
    """
    from .agent_status import router as agent_status_router
    from .skills import router as skills_router
    from .tools import router as tools_router
    from .config import router as config_router
    from .mcp import router as mcp_router
    from .mcp_oauth import router as mcp_oauth_router
    from .workspace import router as workspace_router
    from ..crons.api import router as cron_router
    from ..chats.api import router as chats_router
    from .console import router as console_router
    from .plugins import router as plugins_router
    from .checkpoints import router as checkpoints_router

    router = APIRouter(prefix="/agents/{agentId}", tags=["agent-scoped"])

    # Include all agent-specific sub-routers (they keep their own prefixes)
    # /agents/{agentId}/agent-status -> agent_status_router
    # /agents/{agentId}/chats/* -> chats_router
    # /agents/{agentId}/config/* -> config_router (channels, heartbeat)
    # /agents/{agentId}/cron/* -> cron_router
    # /agents/{agentId}/mcp/* -> mcp_router
    # /agents/{agentId}/skills/* -> skills_router
    # /agents/{agentId}/tools/* -> tools_router
    # /agents/{agentId}/workspace/* -> workspace_router
    router.include_router(agent_status_router)
    router.include_router(chats_router)
    router.include_router(config_router)
    router.include_router(cron_router)
    router.include_router(mcp_oauth_router)
    router.include_router(mcp_router)
    router.include_router(skills_router)
    router.include_router(tools_router)
    router.include_router(workspace_router)
    router.include_router(console_router)
    router.include_router(plugins_router)
    router.include_router(checkpoints_router)

    return router

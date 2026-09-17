# -*- coding: utf-8 -*-
"""Agent-scoped router that wraps existing routers under /agents/{agentId}/

This provides agent isolation by injecting agentId into request.state,
allowing downstream APIs to access the correct agent context.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import Response
from fastapi.responses import ORJSONResponse

from ...access.actor import ActorContext
from ...access.agent_membership import (
    AgentMembershipService,
)
from ...access.agent_repository import (
    AgentResourceRole,
    PostgresAgentRepository,
)
from ...access.capabilities import Capability
from ...access.dependencies import get_actor
from ...access.service import AuthorizationDeniedError, AuthorizationService
from ...config.utils import load_config
from ...identity.runtime import get_identity_schema, is_multi_user_enabled


def _get_agent_membership_service() -> AgentMembershipService:
    return AgentMembershipService(PostgresAgentRepository(schema=get_identity_schema()))


def _allowed_roles_for_request(
    request: Request,
    agent_id: str,
) -> set[AgentResourceRole]:
    """按请求类型区分运行权限与 Agent 配置权限。"""
    from ..agent_context import allowed_agent_roles_for_request

    return allowed_agent_roles_for_request(request, agent_id)


async def require_agent_scoped_access(
    request: Request,
    agentId: str,
    actor: ActorContext = Depends(get_actor),
) -> ActorContext:
    """统一校验 Agent 作用域请求的可信主体和当前资源边界。"""
    try:
        AuthorizationService().require(actor, Capability.AGENT_USE)
    except AuthorizationDeniedError as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc

    if not is_multi_user_enabled():
        return actor

    header_agent_id = request.headers.get("X-Agent-Id")
    if header_agent_id and header_agent_id != agentId:
        raise HTTPException(status_code=403, detail="forbidden")

    agent_ref = load_config().agents.profiles.get(agentId)
    if agent_ref is None or not getattr(agent_ref, "enabled", True):
        raise HTTPException(status_code=403, detail="forbidden")

    from ..agent_context import (
        allows_historical_chat_read,
        authorize_agent_request,
    )

    await authorize_agent_request(
        request,
        agent_id=agentId,
        agent_ref=agent_ref,
        membership_service=_get_agent_membership_service(),
        allowed_roles=_allowed_roles_for_request(request, agentId),
        allow_historical_read_only=allows_historical_chat_read(
            request,
            agentId,
        ),
    )

    return actor


class AgentContextMiddleware(BaseHTTPMiddleware):
    """Middleware to inject agentId into request.state."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Extract agentId and root_session_id from path/headers."""
        import logging
        from ..agent_context import (
            reset_current_agent_id,
            set_current_agent_id,
        )

        logger = logging.getLogger(__name__)
        if request.headers.get("X-Agent-Governance") is not None:
            from ..agent_context import _validate_runtime_config_governance_path

            try:
                _validate_runtime_config_governance_path(request)
            except HTTPException:
                return ORJSONResponse(
                    status_code=403,
                    content={"detail": "forbidden"},
                )
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
        agent_context_token = set_current_agent_id(agent_id)

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

        try:
            return await call_next(request)
        finally:
            reset_current_agent_id(agent_context_token)


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
    from .plugins import agent_settings_router
    from .plan import router as plan_router
    from .user_input import router as user_input_router
    from .runtime_status import router as runtime_status_router
    from .slash import router as slash_router
    from .checkpoints import router as checkpoints_router
    from .attachments import router as attachments_router

    router = APIRouter(
        prefix="/agents/{agentId}",
        tags=["agent-scoped"],
        dependencies=[Depends(require_agent_scoped_access)],
    )

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
    router.include_router(agent_settings_router)
    router.include_router(plan_router)
    router.include_router(user_input_router)
    router.include_router(runtime_status_router)
    router.include_router(slash_router)
    router.include_router(checkpoints_router)
    router.include_router(attachments_router)

    return router

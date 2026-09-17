# -*- coding: utf-8 -*-
"""Agent context utilities for multi-agent support.

Provides utilities to get the correct agent instance for each request.
"""
import asyncio
from contextvars import ContextVar, Token
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from fastapi import HTTPException, Request
from ..access.dependencies import get_actor
from .multi_agent_manager import MultiAgentManager
from ..config.utils import load_config
from ..identity.runtime import is_multi_user_enabled

_RUNTIME_CONFIG_GOVERNANCE_MARKER = "runtime-config"
_RUNTIME_CONFIG_GOVERNANCE_PATHS = frozenset(
    {
        "/workspace/access",
        "/workspace/language",
        "/workspace/running-config",
        "/workspace/running-config/reload",
        "/workspace/running-config/runtime-status",
        "/workspace/running-config/summary",
        "/workspace/running-config/version",
        "/coding-mode",
        "/plan/config",
        "/workspace/project-directory",
        "/workspace/project-directory/list",
        "/workspace/project-directory/create",
        "/workspace/project-directory/clone",
        "/workspace/project-directory/import-local",
        "/workspace/project-directory/upload-zip",
        "/workspace/project-directory/browse-dirs",
        "/workspace/embedding/test",
        "/memory/reindex",
        "/memory/scopes",
        "/memory/graph",
        "/memory/runtime-status",
        "/memory/status",
        "/workspace/memory",
    },
)

if TYPE_CHECKING:
    from .workspace import Workspace

# Context variable to store current agent ID across async calls
_current_agent_id: ContextVar[Optional[str]] = ContextVar(
    "current_agent_id",
    default=None,
)

# Context variable to store current session id across async calls
_current_session_id: ContextVar[Optional[str]] = ContextVar(
    "current_session_id",
    default=None,
)

# Context variable to store current root session id for cross-session approval
_current_root_session_id: ContextVar[Optional[str]] = ContextVar(
    "current_root_session_id",
    default=None,
)

_current_user_id: ContextVar[Optional[str]] = ContextVar(
    "current_user_id",
    default=None,
)

_current_channel: ContextVar[Optional[str]] = ContextVar(
    "current_channel",
    default=None,
)

_current_approval_route: ContextVar[Optional[dict]] = ContextVar(
    "current_approval_route",
    default=None,
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CONFIGURATION_PREFIXES = (
    "/config",
    "/mcp",
    "/skills",
    "/tools",
    "/workspace",
    "/plugins",
    "/checkpoints",
)
_USER_RUNTIME_FILE_WRITE_PATHS = frozenset(
    {
        "/workspace/file-content",
        "/workspace/file-upload",
        "/workspace/upload",
    },
)
_CHECKPOINT_RUNTIME_WRITE_ROUTES = frozenset(
    {
        ("POST", "/workspace/checkpoints/snapshot"),
        ("POST", "/workspace/checkpoints/restore/preview"),
        ("POST", "/workspace/checkpoints/restore"),
        ("POST", "/workspace/checkpoints/gc/preview"),
        ("POST", "/workspace/checkpoints/gc"),
        ("PATCH", "/workspace/checkpoints/auto"),
        ("PATCH", "/workspace/checkpoints/gc/settings"),
        ("DELETE", "/workspace/checkpoints"),
    },
)


def _get_agent_membership_service():
    from ..access.agent_membership import AgentMembershipService
    from ..access.agent_repository import PostgresAgentRepository
    from ..identity.runtime import get_identity_schema

    return AgentMembershipService(PostgresAgentRepository(schema=get_identity_schema()))


def _get_agent_governance_service():
    from ..access.agent_governance import AgentGovernanceService
    from ..access.agent_repository import PostgresAgentRepository
    from ..identity.runtime import get_identity_schema

    return AgentGovernanceService(
        PostgresAgentRepository(schema=get_identity_schema()),
    )


def _normalized_api_path(request: Request) -> str:
    path = request.url.path
    api_path = path[4:] if path.startswith("/api/") else path
    if api_path.startswith("/agents/"):
        parts = api_path.split("/", 3)
        if len(parts) == 4:
            return "/" + parts[3]
    return api_path


def _validate_runtime_config_governance_path(request: Request) -> None:
    marker = getattr(request, "headers", {}).get("X-Agent-Governance")
    if not isinstance(marker, str):
        marker = None
    if marker is None:
        return
    api_path = _normalized_api_path(request)
    allowed = api_path in _RUNTIME_CONFIG_GOVERNANCE_PATHS or api_path.startswith(
        "/workspace/memory/",
    )
    if marker != _RUNTIME_CONFIG_GOVERNANCE_MARKER or not allowed:
        raise HTTPException(status_code=403, detail="forbidden")


def allowed_agent_roles_for_request(request: Request, agent_id: str):
    """按请求路径区分运行权限与 Agent 配置写权限。"""
    from ..access.agent_repository import AgentResourceRole

    resource_path = _normalized_api_path(request)
    hub_endpoint = (
        (request.method.upper(), resource_path)
        in {("GET", "/skills/hub/search"), ("POST", "/skills/hub/install/start")}
        or (
            request.method.upper() == "GET"
            and resource_path.startswith("/skills/hub/install/status/")
            and len(resource_path.split("/")) == 6
        )
        or (
            request.method.upper() == "POST"
            and resource_path.startswith("/skills/hub/install/cancel/")
            and len(resource_path.split("/")) == 6
        )
    )
    if resource_path.startswith("/skills/") and not resource_path.startswith(
        "/skills/pool/",
    ) and resource_path not in {"/skills/pool", "/skills/workspaces"} and not hub_endpoint:
        # Skill source, file and config endpoints expose editable Agent material.
        return {AgentResourceRole.OWNER, AgentResourceRole.COLLABORATOR}

    if request.method.upper() in _SAFE_METHODS:
        return set(AgentResourceRole)

    path = request.url.path
    api_path = path[4:] if path.startswith("/api/") else path
    if api_path == "/workspace/memory" or api_path.startswith(
        "/workspace/memory/",
    ):
        # 公共/私有作用域的最终写权限由记忆服务按 scope 判定；这里必须
        # 允许仅使用成员进入该策略层，否则其私有记忆会被通用配置权限误拦截。
        return set(AgentResourceRole)
    marker = f"/agents/{agent_id}"
    marker_index = api_path.find(marker)
    resource_path = (
        api_path[marker_index + len(marker) :]
        if marker_index >= 0
        else api_path
    )
    if (request.method.upper(), resource_path) in _CHECKPOINT_RUNTIME_WRITE_ROUTES:
        # 检查点路由按可信角色选择私人运行空间，并独立检查创建者和恢复权限。
        # 仅放行已注册的方法/路径；其他工作区配置写入仍须 owner/collaborator。
        return set(AgentResourceRole)
    if (request.method.upper(), resource_path) == ("POST", "/workspace/transcribe"):
        # ASR consumes saved global infrastructure; its handler checks write scope.
        return set(AgentResourceRole)
    if resource_path.startswith("/cron"):
        # Automation routes enforce creator ownership and Agent-owner pause
        # rights at the object layer. All users with live Agent access must
        # reach that layer so they can create and approve their own tasks.
        return set(AgentResourceRole)
    if resource_path in _USER_RUNTIME_FILE_WRITE_PATHS or resource_path.startswith(
        "/workspace/code-files/",
    ):
        # These endpoints can target either the user's private runtime root or
        # the Agent configuration root. Let every usable role reach the router;
        # the resolved root's read_only flag is the authoritative write gate.
        return set(AgentResourceRole)
    if resource_path.startswith(_CONFIGURATION_PREFIXES):
        return {
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
        }
    return set(AgentResourceRole)


def allows_historical_chat_read(request: Request, agent_id: str) -> bool:
    """兼容 Agent-scoped 与旧版 X-Agent-Id 会话只读入口。"""
    if request.method.upper() not in _SAFE_METHODS:
        return False
    path = request.url.path
    return path.startswith("/api/chats") or (
        f"/agents/{agent_id}/chats" in path
    )


async def authorize_agent_request(
    request: Request,
    *,
    agent_id: str,
    agent_ref,
    membership_service=None,
    allowed_roles=None,
    allow_historical_read_only: bool = False,
):
    """在多用户模式下统一校验当前请求对目标 Agent 的访问权。"""
    from ..access.agent_membership import AgentAccessDeniedError
    from ..access.agent_repository import LegacyAgentRecord
    from ..access.capabilities import Capability
    from ..access.dependencies import get_actor
    from ..access.service import AuthorizationDeniedError, AuthorizationService

    actor = get_actor(request)
    try:
        AuthorizationService().require(actor, Capability.AGENT_USE)
        service = membership_service or _get_agent_membership_service()
        effective_roles = allowed_roles or allowed_agent_roles_for_request(
            request,
            agent_id,
        )
        access = await service.require_role(
            actor=actor,
            agent=LegacyAgentRecord(
                key=agent_id,
                name=agent_id,
                description="",
                workspace_key=getattr(agent_ref, "workspace_dir", ""),
                status="active",
            ),
            allowed_roles=effective_roles,
            allow_historical_read_only=allow_historical_read_only,
        )
    except (AuthorizationDeniedError, AgentAccessDeniedError) as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc

    request.state.agent_access = access
    return access


async def get_agent_for_request(
    request: Request,
    agent_id: Optional[str] = None,
) -> "Workspace":
    """Get agent workspace for current request.

    Priority:
    1. agent_id parameter (explicit override)
    2. request.state.agent_id (from agent-scoped router)
    3. X-Agent-Id header (from frontend)
    4. Active agent from config

    Args:
        request: FastAPI request object
        agent_id: Agent ID override (highest priority)

    Returns:
        Workspace for the specified or active agent

    Raises:
        HTTPException: If agent not found
    """
    _validate_runtime_config_governance_path(request)

    # Determine which agent to use
    target_agent_id = agent_id

    # Check request.state.agent_id (set by agent-scoped router)
    if not target_agent_id and hasattr(request.state, "agent_id"):
        target_agent_id = request.state.agent_id

    # Check X-Agent-Id header
    if not target_agent_id:
        target_agent_id = request.headers.get("X-Agent-Id")

    # Load config once for fallback and validation
    config = None
    if not target_agent_id:
        # Fallback to active agent from config
        config = load_config()
        target_agent_id = config.agents.active_agent or "default"

    # Check if agent exists and is enabled
    if config is None:
        config = load_config()
    if target_agent_id not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{target_agent_id}' not found",
        )

    agent_ref = config.agents.profiles[target_agent_id]
    if not getattr(agent_ref, "enabled", True):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{target_agent_id}' is disabled",
        )

    if is_multi_user_enabled() and not hasattr(request.state, "agent_access"):
        await authorize_agent_request(
            request,
            agent_id=target_agent_id,
            agent_ref=agent_ref,
            allow_historical_read_only=allows_historical_chat_read(
                request,
                target_agent_id,
            ),
        )

    # Get MultiAgentManager
    if not hasattr(request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )

    manager: MultiAgentManager = request.app.state.multi_agent_manager

    try:
        workspace = await manager.get_agent(target_agent_id)
        if not workspace:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{target_agent_id}' not found",
            )
        return workspace
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent: {str(e)}",
        ) from e


async def get_running_config_workspace(
    request: Request,
    *,
    action: str,
) -> "Workspace":
    """解析普通成员访问或管理员显式代管的运行配置目标。"""
    _validate_runtime_config_governance_path(request)
    marker = getattr(request, "headers", {}).get("X-Agent-Governance")
    if not isinstance(marker, str):
        marker = None
    if marker is None:
        return await get_agent_for_request(request)

    target_agent_id = (request.headers.get("X-Agent-Id") or "").strip()
    if not target_agent_id or not is_multi_user_enabled():
        raise HTTPException(status_code=403, detail="forbidden")

    from ..access.agent_governance import AgentGovernanceDeniedError
    agent_ref = load_config().agents.profiles.get(target_agent_id)
    if agent_ref is None or not getattr(agent_ref, "enabled", True):
        raise HTTPException(status_code=403, detail="forbidden")

    try:
        governance = await _get_agent_governance_service().require_admin_agent(
            actor=get_actor(request),
            agent_key=target_agent_id,
            action=action,
        )
    except (AgentGovernanceDeniedError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc

    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    try:
        workspace = await manager.get_agent(target_agent_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="agent_not_found") from exc
    if workspace is None:
        raise HTTPException(status_code=404, detail="agent_not_found")

    request.state.agent_governance = governance
    request.state.agent_id = target_agent_id
    return workspace


def require_running_config_editor(request: Request) -> None:
    """要求当前请求具备完整运行配置的查看和编辑权限。"""
    state = getattr(request, "state", None)
    if state is None:
        return
    values = vars(state)
    nested = values.get("_state")
    if isinstance(nested, dict):
        values = nested
    if values.get("agent_governance") is not None:
        return
    access = values.get("agent_access")
    if access is None:
        return
    role = getattr(access, "role", None)
    role_value = getattr(role, "value", role)
    if role_value not in {"owner", "collaborator"} or bool(
        getattr(access, "historical_read_only", False),
    ):
        raise HTTPException(status_code=403, detail="forbidden")


def get_agent_project_dir(workspace: "Workspace") -> Path:
    """Return the agent's default project directory.

    The Coding tools switch does not participate in directory resolution.
    """
    from ..config.config import load_agent_config
    from ..services.project_directory import resolve_effective_project_dir

    try:
        config = load_agent_config(workspace.agent_id)
        project_dir = config.project_dir
    except Exception:
        project_dir = None

    return resolve_effective_project_dir(
        workspace.workspace_dir,
        agent_project_dir=project_dir,
    )[0]


async def get_project_dir_for_request(
    request: Request,
    workspace: "Workspace",
) -> Path:
    """Resolve the effective project directory for a Files API request."""
    from fastapi import HTTPException
    from ..config.config import load_agent_config
    from ..services.project_directory import (
        resolve_effective_project_dir,
        session_project_dir,
    )

    session_override = None
    pending_override = None
    chat_id = request.headers.get("X-Chat-Id")
    if chat_id:
        chat = await workspace.chat_manager.get_chat(chat_id)
        if chat is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Chat not found")
        conversation_repository = workspace.chat_manager.conversation_repository
        if conversation_repository is not None:
            try:
                actor_user_id = get_actor(request).user_id
                conversation = await conversation_repository.with_user(
                    actor_user_id
                ).get_conversation(UUID(chat.id))
            except (TypeError, ValueError):
                conversation = None
            if (
                conversation is not None
                and conversation.owner_user_id == actor_user_id
                and conversation.shared_app_id is not None
                and conversation.publication_id is not None
            ):
                from ..constant import WORKING_DIR
                from ..workspaces import WorkspaceResolver

                resolved = WorkspaceResolver(
                    working_dir=WORKING_DIR
                ).resolve_shared_app_runtime(
                    user_id=actor_user_id,
                    shared_app_id=conversation.shared_app_id,
                    publication_id=conversation.publication_id,
                )
                if not resolved.path.is_dir():
                    raise HTTPException(
                        status_code=409,
                        detail="Shared app workspace is unavailable",
                    )
                return resolved.path
        session_override = session_project_dir(chat.meta)
        if is_multi_user_enabled():
            from ..access.agent_repository import agent_database_id, AgentResourceRole
            from ..services.workspace_files import resolve_private_task_directory

            if (conversation_repository is None or conversation is None
                or conversation.owner_user_id != actor_user_id
                or conversation.agent_id != agent_database_id(workspace.agent_id)):
                raise HTTPException(status_code=404, detail="Chat not found")
            role, _ = get_agent_access_state(request)
            if not session_override or role is AgentResourceRole.USER:
                return await asyncio.to_thread(
                    resolve_private_task_directory,
                    actor_user_id=actor_user_id,
                    agent_id=workspace.agent_id,
                    conversation_id=str(chat.id),
                )
    else:
        pending_override = request.headers.get("X-Session-Project-Dir")

    def _resolve() -> Path:
        try:
            config = load_agent_config(workspace.agent_id)
            agent_project_dir = config.project_dir
        except Exception:
            agent_project_dir = None
        resolved_override = session_override
        if not chat_id and pending_override:
            pending_path = Path(pending_override).expanduser().resolve()
            if not pending_path.is_dir():
                raise NotADirectoryError(str(pending_path))
            resolved_override = str(pending_path)
        return resolve_effective_project_dir(
            workspace.workspace_dir,
            agent_project_dir=agent_project_dir,
            session_override=resolved_override,
        )[0]

    try:
        return await asyncio.to_thread(_resolve)
    except NotADirectoryError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"Project directory is unavailable: {exc}",
        ) from exc


def get_agent_access_state(request: Request):
    """返回当前请求已授权的 Agent 资源角色与历史只读状态。"""
    from ..access.agent_repository import AgentResourceRole

    access = getattr(getattr(request, "state", None), "agent_access", None)
    role = getattr(access, "role", AgentResourceRole.OWNER)
    if not isinstance(role, AgentResourceRole):
        role = AgentResourceRole(getattr(role, "value", role))
    return role, bool(getattr(access, "historical_read_only", False))


async def get_files_workspace_access(
    request: Request,
    workspace: "Workspace",
    *,
    agent_project: Path | None = None,
):
    """解析 Files 页面项目运行目录与 Agent 配置目录的独立权限。"""
    from ..access.agent_repository import AgentResourceRole
    from ..identity.runtime import get_identity_schema
    from ..persistence.agent_user_workspaces import (
        AgentUserWorkspaceRepository,
    )
    from ..services.workspace_files import resolve_files_workspace_access

    actor = get_actor(request)
    role, historical_read_only = get_agent_access_state(request)
    access = resolve_files_workspace_access(
        agent_id=workspace.agent_id,
        agent_workspace=workspace.workspace_dir,
        agent_project=(
            agent_project
            if agent_project is not None
            else await get_project_dir_for_request(request, workspace)
        ),
        actor_user_id=actor.user_id,
        access_role=role,
        historical_read_only=historical_read_only,
        agent_workspace_kind=getattr(workspace, "workspace_kind", "legacy"),
    )
    if access.project.kind == "user_runtime":
        if actor.user_id is None or role is not AgentResourceRole.USER:
            raise HTTPException(status_code=403, detail="forbidden")
        await AgentUserWorkspaceRepository(
            schema=get_identity_schema(),
        ).ensure_private(
            user_id=actor.user_id,
            agent_key=workspace.agent_id,
            workspace_key=access.project.workspace_key or "",
        )
        if request.headers.get("X-Chat-Id"):
            from dataclasses import replace

            access = replace(access, project=replace(
                access.project,
                path=await get_project_dir_for_request(request, workspace),
            ))
    return access


def get_active_agent_id() -> str:
    """Get current active agent ID from config.

    Returns:
        Active agent ID, defaults to "default"
    """
    try:
        config = load_config()
        return config.agents.active_agent or "default"
    except Exception:
        return "default"


def set_current_agent_id(agent_id: Optional[str]) -> Token[Optional[str]]:
    """Set current agent ID in context.

    Args:
        agent_id: Agent ID to set
    """
    return _current_agent_id.set(agent_id)


def reset_current_agent_id(token: Token[Optional[str]]) -> None:
    """Restore the Agent context that existed before the current scope."""
    _current_agent_id.reset(token)


def get_current_agent_id() -> str:
    """Get current agent ID from context or config fallback.

    Returns:
        Current agent ID, defaults to active agent or "default"
    """
    agent_id = _current_agent_id.get()
    if agent_id:
        return agent_id
    return get_active_agent_id()


def set_current_session_id(session_id: str) -> None:
    _current_session_id.set(session_id)


@contextmanager
def scoped_session_id(session_id: str) -> Iterator[None]:
    """Temporarily expose one session through the request context."""
    token = _current_session_id.set(session_id)
    try:
        yield
    finally:
        _current_session_id.reset(token)


def get_current_session_id() -> Optional[str]:
    return _current_session_id.get()


def set_current_root_session_id(root_session_id: Optional[str]) -> None:
    """Set current root session ID in context.

    Args:
        root_session_id: Root session ID to set
    """
    _current_root_session_id.set(root_session_id)


def get_current_root_session_id() -> Optional[str]:
    """Get current root session ID from context.

    Returns:
        Root session ID or None
    """
    return _current_root_session_id.get()


def set_current_user_id(user_id: Optional[str]) -> None:
    """Set current user ID in context."""
    _current_user_id.set(user_id)


def get_current_user_id() -> Optional[str]:
    """Get current user ID from context."""
    return _current_user_id.get()


def set_current_channel(channel: Optional[str]) -> None:
    """Set current channel in context."""
    _current_channel.set(channel)


def get_current_channel() -> Optional[str]:
    """Get current channel from context."""
    return _current_channel.get()


def set_current_approval_route(route: Optional[dict]) -> None:
    """Set routing metadata used only for spawned-child approvals."""
    _current_approval_route.set(route)


def get_current_approval_route() -> Optional[dict]:
    """Return routing metadata used only for spawned-child approvals."""
    return _current_approval_route.get()

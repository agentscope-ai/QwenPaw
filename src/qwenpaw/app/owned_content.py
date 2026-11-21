"""解析本人内容的导航作用域；不授予智能体运行或配置权限。"""

from fastapi import HTTPException, Request

from ..access.dependencies import get_actor
from ..config import load_config
from ..workspaces.resolver import WorkspaceKind, WorkspaceResolver


def owner_agent_key(request: Request) -> str:
    """验证导航中的 Agent key；所有内容仍须由仓储核验当前用户归属。"""
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(401, "not_authenticated")
    scoped = request.path_params.get("agentId")
    selected = request.headers.get("X-Agent-Id")
    if scoped and selected and scoped != selected:
        raise HTTPException(400, "agent_scope_mismatch")
    agent_key = scoped or getattr(request.state, "agent_id", None) or selected
    if not agent_key:
        agent_key = load_config().agents.active_agent or "default"
    try:
        WorkspaceResolver().resolve(
            kind=WorkspaceKind.USER_RUNTIME, resource_id=agent_key,
            actor_user_id=actor.user_id,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "invalid_agent_id") from exc
    return agent_key

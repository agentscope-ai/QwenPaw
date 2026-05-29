# -*- coding: utf-8 -*-
"""Agent context utilities for multi-agent support.

Provides utilities to get the correct agent instance for each request.
"""
from contextvars import ContextVar
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from fastapi import Request
from .multi_agent_manager import MultiAgentManager
from ..config.utils import load_config

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
    from fastapi import HTTPException

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


def get_coding_dir(workspace: "Workspace") -> Path:
    """Return the active coding project directory for *workspace*.

    If the agent has set a ``coding_mode.project_dir`` in its config, that
    path is returned.  Otherwise the agent's default ``workspace_dir`` is used.
    """
    from ..config.config import load_agent_config

    try:
        config = load_agent_config(workspace.agent_id)
        project_dir = (
            config.coding_mode.project_dir if config.coding_mode else None
        )
    except Exception:  # noqa: BLE001
        project_dir = None

    if project_dir:
        return Path(project_dir).expanduser().resolve()
    return workspace.workspace_dir


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


def set_current_agent_id(agent_id: str) -> None:
    """Set current agent ID in context.

    Args:
        agent_id: Agent ID to set
    """
    _current_agent_id.set(agent_id)


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

# -*- coding: utf-8 -*-
"""Context variable for agent workspace directory.

This module provides a context variable to pass the agent's workspace
directory to tool functions, allowing them to resolve relative paths
correctly in a multi-agent environment.
"""
from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentscope.state import AgentState
    from agentscope.tool import Toolkit

# Context variable to store the current agent's workspace directory
current_workspace_dir: ContextVar[Path | None] = ContextVar(
    "current_workspace_dir",
    default=None,
)

current_project_dir: ContextVar[Path | None] = ContextVar(
    "current_project_dir",
    default=None,
)


def get_current_workspace_dir() -> Path | None:
    """Get the current agent's workspace directory from context.

    Returns:
        Path to the current agent's workspace directory, or None if not set.
    """
    return current_workspace_dir.get()


def set_current_workspace_dir(workspace_dir: Path | None) -> None:
    """Set the current agent's workspace directory in context.

    Args:
        workspace_dir: Path to the agent's workspace directory.
    """
    current_workspace_dir.set(workspace_dir)


def get_current_project_dir() -> Path | None:
    """Get the effective project directory for the current turn."""
    return current_project_dir.get()


def set_current_project_dir(project_dir: Path | None) -> None:
    """Set the immutable effective project directory for the current turn."""
    current_project_dir.set(project_dir)


# Context variable to store the recent_max_bytes limit
current_recent_max_bytes: ContextVar[int | None] = ContextVar(
    "current_recent_max_bytes",
    default=None,
)


def get_current_recent_max_bytes() -> int | None:
    """Get the current agent's recent_max_bytes limit from context.

    Returns:
        Byte limit for recent tool output truncation, or None if not set.
    """
    return current_recent_max_bytes.get()


def set_current_recent_max_bytes(max_bytes: int | None) -> None:
    """Set the current agent's recent_max_bytes limit in context.

    Args:
        max_bytes: Byte limit for recent tool output truncation.
    """
    current_recent_max_bytes.set(max_bytes)


# Context variable to store the configured shell command timeout
current_shell_command_timeout: ContextVar[float | None] = ContextVar(
    "current_shell_command_timeout",
    default=None,
)


def get_current_shell_command_timeout() -> float | None:
    """Get the configured default timeout for execute_shell_command.

    Returns:
        Timeout in seconds, or None if not configured.
    """
    return current_shell_command_timeout.get()


def set_current_shell_command_timeout(timeout: float | None) -> None:
    """Set the configured default timeout for execute_shell_command.

    Args:
        timeout: Timeout in seconds.
    """
    current_shell_command_timeout.set(timeout)


current_shell_command_executable: ContextVar[str | None] = ContextVar(
    "current_shell_command_executable",
    default=None,
)


def get_current_shell_command_executable() -> str | None:
    """Get the configured shell executable for execute_shell_command.

    Returns:
        Path to the shell executable, or None if not configured.
    """
    return current_shell_command_executable.get()


def set_current_shell_command_executable(executable: str | None) -> None:
    """Set the configured shell executable for execute_shell_command.

    Args:
        executable: Path to the shell executable (e.g. "/bin/bash").
    """
    current_shell_command_executable.set(executable)


# Context variable to store the current session ID for tool functions
current_session_id: ContextVar[str | None] = ContextVar(
    "current_session_id",
    default=None,
)


def get_current_session_id() -> str | None:
    """Get the current session ID from context.

    Returns:
        Current session ID, or None if not set.
    """
    return current_session_id.get()


def set_current_session_id(session_id: str | None) -> None:
    """Set the current session ID in context.

    Args:
        session_id: Session ID to store in context.
    """
    current_session_id.set(session_id)


# Context variable to store the current agent's Toolkit instance
current_toolkit: ContextVar[Toolkit | None] = ContextVar(
    "current_toolkit",
    default=None,
)


def get_current_toolkit() -> Toolkit | None:
    """Get the current agent's Toolkit instance from context.

    Returns:
        The current Toolkit instance, or None if not set.
    """
    return current_toolkit.get()


def set_current_toolkit(toolkit: Toolkit | None) -> None:
    """Set the current agent's Toolkit instance in context.

    Args:
        toolkit: Toolkit instance to store in context.
    """
    current_toolkit.set(toolkit)


# Context variable to store the current agent's AgentState instance.
# Set per-request by ContextVarsSetupHook so that sub-tool calls
# (e.g. run_tool_batch) can invoke toolkit.call_tool() with the
# correct state for permission checking and state injection.
current_agent_state: ContextVar[AgentState | None] = ContextVar(
    "current_agent_state",
    default=None,
)


def get_current_agent_state() -> AgentState | None:
    """Get the current agent's AgentState from context.

    Returns:
        The current AgentState instance, or None if not set.
    """
    return current_agent_state.get()


def set_current_agent_state(state: AgentState | None) -> None:
    """Set the current agent's AgentState in context.

    Args:
        state: AgentState instance to store in context.
    """
    current_agent_state.set(state)


# Session-level registry for mail F1 exploration mode (step-by-step
# approval). A module-level dict is used instead of a ContextVar on
# purpose: the tool coordinator runs every tool call in its own asyncio
# task (asyncio.create_task copies the context), so a ContextVar written
# inside the activation tool would stay isolated in that child task and
# never be visible to subsequent tool calls. Single-key dict reads and
# writes (``d[k] = v``/``d.pop``/``in``) are atomic under the GIL, which
# is sufficient for concurrent tool tasks.
# Maps session_id -> latest "reasoning" text the agent emitted before a
# tool call (empty string right after activation).
_f1_sessions: dict[str, str] = {}

_F1_REASONING_MAX_CHARS = 200


def activate_f1_for_session(session_id: str) -> None:
    """Mark mail F1 exploration mode active for the given session.

    Args:
        session_id: Session ID for which F1 mode is activated.
    """
    _f1_sessions[session_id] = ""


def is_f1_active_for_session(session_id: str | None) -> bool:
    """Return whether mail F1 exploration mode is active for a session.

    Args:
        session_id: Session ID to check. Falsy values return False.
    """
    if not session_id:
        return False
    return session_id in _f1_sessions


def deactivate_f1_for_session(session_id: str | None) -> None:
    """Clear mail F1 exploration mode for the given session.

    Args:
        session_id: Session ID to deactivate. Falsy values are a no-op.
    """
    if session_id:
        _f1_sessions.pop(session_id, None)


def set_f1_reasoning(session_id: str | None, text: str) -> None:
    """Store the latest tool-call reasoning text for an active F1 session.

    No-op when the session is not in F1 mode. The text is stripped and
    truncated to a display-friendly length.

    Args:
        session_id: Session ID whose reasoning is being recorded.
        text: Assistant text emitted before the upcoming tool call.
    """
    if not session_id or session_id not in _f1_sessions:
        return
    _f1_sessions[session_id] = text.strip()[:_F1_REASONING_MAX_CHARS]


def get_f1_reasoning(session_id: str | None) -> str:
    """Return the latest reasoning text for an F1 session.

    Args:
        session_id: Session ID to look up. Falsy or inactive sessions
            return an empty string.
    """
    if not session_id:
        return ""
    return _f1_sessions.get(session_id, "")

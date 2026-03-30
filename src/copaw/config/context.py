# -*- coding: utf-8 -*-
"""Context variable for agent workspace directory.

This module provides a context variable to pass the agent's workspace
directory to tool functions, allowing them to resolve relative paths
correctly in a multi-agent environment.
"""
from contextvars import ContextVar
from pathlib import Path

# Context variable to store the current agent's workspace directory
current_workspace_dir: ContextVar[Path | None] = ContextVar(
    "current_workspace_dir",
    default=None,
)

# Context variable for the current focus-level working directory (e.g. a
# pipeline workspace subdirectory or a project directory). It takes
# precedence over current_workspace_dir for user-facing file tools so that
# the agent is scoped to the active focus while system tools still use
# workspace_dir.
current_focus_dir: ContextVar[Path | None] = ContextVar(
    "current_focus_dir",
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


def get_current_focus_dir() -> Path | None:
    """Get the current focus-level working directory from context.

    Returns:
        Path to the current focus directory (e.g. pipeline workspace or
        project directory), or None if not set.
    """
    return current_focus_dir.get()


def set_current_focus_dir(focus_dir: Path | None) -> None:
    """Set the current focus-level working directory in context.

    Args:
        focus_dir: Path to the focus directory. Pass ``None`` to clear and
            fall back to workspace_dir.
    """
    current_focus_dir.set(focus_dir)


def get_current_task_dir() -> Path | None:
    """Backward-compatible alias for get_current_focus_dir()."""
    return get_current_focus_dir()


def set_current_task_dir(task_dir: Path | None) -> None:
    """Backward-compatible alias for set_current_focus_dir()."""
    set_current_focus_dir(task_dir)

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

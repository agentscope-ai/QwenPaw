# -*- coding: utf-8 -*-
"""Workspace-level restart logic.

This module provides workspace-scoped restart functionality for the
/daemon restart command. Each workspace can reload its own components
(channels, cron, MCP) without affecting other workspaces.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


async def restart_workspace(workspace: "Workspace") -> None:
    """Restart a single workspace's components (channels, cron, MCP).

    This function performs an in-process reload of workspace components:
    1. Reloads agent configuration from agent.json
    2. Calls workspace.reload() to restart managers

    Args:
        workspace: The workspace instance to restart

    Raises:
        Exception: If restart fails
    """
    logger.info(f"Restarting workspace: {workspace.agent_id}")

    try:
        # Reload the workspace (hot reload all managers)
        await workspace.reload()

        logger.info(
            f"Workspace restart completed: {workspace.agent_id}",
        )

    except Exception as e:
        logger.exception(
            f"Failed to restart workspace {workspace.agent_id}: {e}",
        )
        raise


def create_restart_callback(workspace: "Workspace"):
    """Create a restart callback for a workspace's runner.

    This creates a closure that captures the workspace instance and
    provides it as a callback for the /daemon restart command.

    Args:
        workspace: The workspace instance

    Returns:
        Async callable that restarts the workspace
    """

    async def _restart_callback() -> None:
        """Restart callback for runner."""
        await restart_workspace(workspace)

    return _restart_callback

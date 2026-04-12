# -*- coding: utf-8 -*-
"""Utility functions for app routers."""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request
    from .multi_agent_manager import MultiAgentManager

logger = logging.getLogger(__name__)


def schedule_agent_reload(request: "Request", agent_id: str) -> None:
    """Schedule an agent reload in background (non-blocking).

    This is a common pattern used across multiple endpoints to reload
    agent configuration after making changes. The reload happens
    asynchronously without blocking the API response.

    IMPORTANT: This function extracts manager and agent_id from the
    request context before creating the background task, to avoid
    accessing request/workspace objects after their lifecycle ends.

    Args:
        request: FastAPI request object (must have multi_agent_manager)
        agent_id: Agent ID to reload

    Example:
        >>> from qwenpaw.app.utils import schedule_agent_reload
        >>> save_agent_config(workspace.agent_id, agent_config)
        >>> schedule_agent_reload(request, workspace.agent_id)
    """
    # Extract manager before creating background task (defensive)
    manager: "MultiAgentManager" = getattr(
        request.app.state,
        "multi_agent_manager",
        None,
    )

    if manager is None:
        logger.warning(
            f"Cannot schedule agent reload for '{agent_id}': "
            "MultiAgentManager not initialized in app state",
        )
        return

    async def reload_in_background():
        try:
            await manager.reload_agent(agent_id)
        except Exception as e:
            logger.warning(
                f"Background reload failed for agent '{agent_id}': {e}",
                exc_info=True,
            )

    asyncio.create_task(reload_in_background())

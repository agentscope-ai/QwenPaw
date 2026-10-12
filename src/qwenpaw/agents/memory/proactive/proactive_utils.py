# -*- coding: utf-8 -*-
"""Idle-detection helpers for proactive agenda delivery.

Topic production moved to ReMe's proactive chain, so this module no longer
scrapes chat history or captures the screen.  It only answers the two
questions the idle trigger asks about the running workspace: is the agent
busy, and when did the user last say something.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ....app.workspace import Workspace

logger = logging.getLogger(__name__)


async def is_agent_busy(
    workspace: "Workspace",
) -> bool:
    """Check if the agent is currently busy processing tasks."""
    try:
        if hasattr(workspace, "task_tracker") and workspace.task_tracker:
            active_tasks = await workspace.task_tracker.has_active_tasks()
            return active_tasks
        return False
    except Exception as e:
        logger.error(f"Error checking if agent is busy: {e}")
        return False


def ensure_tz_aware(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware, convert naive datetime to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_last_message_ts(
    workspace: "Workspace" = None,
) -> Optional[float]:
    """Get the timestamp of the last message."""

    if workspace:
        try:
            chats = await workspace.chat_manager.list_chats()
            latest_update_ts = None
            for session in chats:
                updated_at_dt = ensure_tz_aware(session.updated_at)
                ts = updated_at_dt.timestamp()
                if latest_update_ts is None or ts > latest_update_ts:
                    latest_update_ts = ts
            return latest_update_ts
        except Exception as e:
            logger.warning("Cannot read chats from workspace: %s", e)

    return None

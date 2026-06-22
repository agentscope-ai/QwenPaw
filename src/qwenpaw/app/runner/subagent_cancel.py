# -*- coding: utf-8 -*-
"""Cancellation bridge for linked background subagents."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from .subagent_events import get_subagent_event_registry

logger = logging.getLogger(__name__)

_cancel_task_callback: Optional[Callable[[str], Awaitable[bool]]] = None


def set_subagent_task_cancel_callback(
    callback: Callable[[str], Awaitable[bool]],
) -> None:
    """Register the runtime-specific task cancellation function."""
    global _cancel_task_callback
    _cancel_task_callback = callback


async def cancel_linked_subagents(parent_session_id: str) -> int:
    """Cancel all linked running subagents for a parent session."""
    if not parent_session_id:
        return 0
    if _cancel_task_callback is None:
        logger.debug(
            "No subagent task cancel callback registered; session=%s",
            parent_session_id[:30],
        )
        return 0

    registry = get_subagent_event_registry()
    task_ids = registry.linked_running_task_ids(parent_session_id)
    cancelled = 0
    for task_id in task_ids:
        try:
            if await _cancel_task_callback(task_id):
                cancelled += 1
        except Exception:
            logger.debug(
                "Failed to cancel linked subagent task_id=%s",
                task_id,
                exc_info=True,
            )
    return cancelled


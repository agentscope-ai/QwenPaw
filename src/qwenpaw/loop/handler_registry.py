# -*- coding: utf-8 -*-
"""Shared StopHandler factory for workspace.

Single entry point for GoalMode, ReAct gates, and
future plugin-registered modes to obtain or create
a StopHandler on a workspace object.
"""
from __future__ import annotations

import logging
from typing import Any

from .gates import (
    StopHandler,
    StopHandlerRegistration,
)

logger = logging.getLogger(__name__)


def get_or_create_stop_handler(
    workspace: Any,
    *,
    plugin_id: str = "__universal__",
    name: str = "universal-stop-handler",
    scope: str = "",
    priority: int = 0,
) -> StopHandler:
    """Get or create StopHandler on workspace.

    If a StopHandler already exists on
    ``workspace._stop_handler``, it is returned
    without creating a second registration.

    Args:
        workspace: The workspace/agent-workspace.
        plugin_id: Identifier for the registration.
        name: Human-readable handler name.
        scope: Scope for handler filtering.
            "" = always runs; "default" = skipped
            when a mode-specific scope is active.
        priority: Handler priority (lower = first).

    Returns:
        The StopHandler instance.
    """
    existing = getattr(
        workspace,
        "_stop_handler",
        None,
    )
    if isinstance(existing, StopHandler):
        return existing

    handler = StopHandler()
    setattr(workspace, "_stop_handler", handler)

    plugins = getattr(workspace, "plugins", None)
    if plugins is not None:
        if not hasattr(plugins, "stop_handlers"):
            plugins.stop_handlers = []
        plugins.stop_handlers.append(
            StopHandlerRegistration(
                plugin_id=plugin_id,
                handler=handler,
                priority=priority,
                name=name,
                scope=scope,
            ),
        )
    else:
        logger.warning(
            "No plugins attr on workspace",
        )
    return handler


__all__ = ["get_or_create_stop_handler"]

# -*- coding: utf-8 -*-
"""Loop management API — list available loops.

Endpoints:
    GET /api/loops — list all available loops
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/loops", tags=["loops"])

BUILTIN_LOOP = {
    "name": "goal",
    "slash_command": "goal",
    "description": "Set a goal — agent works until done.",
    "source": "builtin",
}


@router.get("")
async def list_loops() -> list[dict[str, Any]]:
    """List all available loops (builtin + plugin)."""
    result: list[dict[str, Any]] = [BUILTIN_LOOP]

    plugin_loops = _list_plugin_loops()
    result.extend(plugin_loops)

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for loop in result:
        key = loop.get("slash_command", loop["name"])
        if key not in seen:
            seen.add(key)
            deduped.append(loop)
    return deduped


def _list_plugin_loops() -> list[dict[str, Any]]:
    """List loops registered by plugins."""
    result: list[dict[str, Any]] = []
    try:
        from ...plugins.registry import PluginRegistry

        mgr = PluginRegistry().get_workspace_manager()
        if mgr is None:
            return result
        for ws in getattr(
            mgr,
            "workspaces",
            {},
        ).values():
            plugins = getattr(ws, "plugins", None)
            if plugins is None:
                continue
            for h in getattr(
                plugins,
                "stop_handlers",
                [],
            ):
                meta = getattr(h, "metadata", {})
                if meta.get("loop_name"):
                    result.append(
                        {
                            "name": meta["loop_name"],
                            "slash_command": meta.get(
                                "slash_command",
                                meta["loop_name"],
                            ),
                            "description": meta.get(
                                "description",
                                "",
                            ),
                            "source": "plugin",
                        },
                    )
    except Exception as exc:
        logger.warning(
            "Failed to list plugin loops: %s",
            exc,
        )
    return result

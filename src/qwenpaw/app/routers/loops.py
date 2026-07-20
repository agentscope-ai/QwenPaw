# -*- coding: utf-8 -*-
"""Loop discovery, catalog, and custom mode persistence APIs."""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from ...config.config import CustomLoopModeConfig, save_agent_config
from ...loop.catalog import get_gate_catalog
from ...loop.compiler import compile_loop_mode
from ..agent_context import get_agent_for_request
from ..utils import schedule_agent_reload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/loops", tags=["loops"])

BUILTIN_LOOPS = [
    {
        "name": "default",
        "slash_command": "",
        "description": "The standard guarded agent loop.",
        "source": "builtin",
    },
    {
        "name": "goal",
        "slash_command": "goal",
        "description": "Set a goal and work until it is done.",
        "source": "builtin",
    },
    {
        "name": "mission",
        "slash_command": "mission",
        "description": "Run a persistent multi-step mission.",
        "source": "builtin",
    },
]


@router.get("")
async def list_loops(request: Request) -> list[dict[str, Any]]:
    """List built-in, custom, and plugin-provided loops."""
    result = [dict(item) for item in BUILTIN_LOOPS]
    workspace = await get_agent_for_request(request)
    for mode in workspace.config.running.loop.custom_modes:
        if not mode.enabled:
            continue
        result.append(
            {
                "name": mode.name,
                "slash_command": mode.slash_command,
                "description": mode.description,
                "source": "custom",
                "id": mode.id,
            },
        )
    result.extend(_list_plugin_loops())
    return _deduplicate(result)


@router.get("/gates/catalog")
async def list_gate_catalog() -> list[dict[str, Any]]:
    """Return the explicit built-in gate catalog."""
    return get_gate_catalog().describe()


@router.get("/custom", response_model=list[CustomLoopModeConfig])
async def list_custom_modes(request: Request) -> list[CustomLoopModeConfig]:
    """Return every saved custom loop mode for the current agent."""
    workspace = await get_agent_for_request(request)
    return workspace.config.running.loop.custom_modes


@router.post(
    "/custom",
    response_model=CustomLoopModeConfig,
    status_code=status.HTTP_201_CREATED,
)
async def create_custom_mode(
    request: Request,
    mode: CustomLoopModeConfig,
) -> CustomLoopModeConfig:
    """Validate and append one complete custom mode."""
    workspace = await get_agent_for_request(request)
    modes = list(workspace.config.running.loop.custom_modes)
    if any(item.id == mode.id for item in modes):
        raise HTTPException(status_code=409, detail="Mode ID already exists")
    _validate_mode(mode, workspace, modes)
    modes.append(mode)
    _persist_modes(request, workspace, modes)
    return mode


@router.put("/custom/{mode_id}", response_model=CustomLoopModeConfig)
async def update_custom_mode(
    request: Request,
    mode_id: str,
    mode: CustomLoopModeConfig,
) -> CustomLoopModeConfig:
    """Atomically replace one custom mode."""
    if mode.id != mode_id:
        raise HTTPException(status_code=422, detail="Mode ID cannot change")
    workspace = await get_agent_for_request(request)
    modes = list(workspace.config.running.loop.custom_modes)
    index = _find_mode(modes, mode_id)
    others = [item for item in modes if item.id != mode_id]
    _validate_mode(mode, workspace, others, ignored_mode=modes[index])
    modes[index] = mode
    _persist_modes(request, workspace, modes)
    return mode


@router.delete("/custom/{mode_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_mode(request: Request, mode_id: str) -> None:
    """Delete one saved custom mode."""
    workspace = await get_agent_for_request(request)
    modes = list(workspace.config.running.loop.custom_modes)
    index = _find_mode(modes, mode_id)
    modes.pop(index)
    _persist_modes(request, workspace, modes)


@router.post(
    "/custom/{mode_id}/duplicate",
    response_model=CustomLoopModeConfig,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_custom_mode(
    request: Request,
    mode_id: str,
) -> CustomLoopModeConfig:
    """Create a disabled copy with unique identity and command."""
    workspace = await get_agent_for_request(request)
    modes = list(workspace.config.running.loop.custom_modes)
    source = modes[_find_mode(modes, mode_id)]
    copy = deepcopy(source)
    copy.id = _unique_value(f"{source.id}-copy", {item.id for item in modes})
    copy.name = f"{source.name} Copy"
    copy.slash_command = _unique_value(
        f"{source.slash_command}-copy",
        {item.slash_command for item in modes},
    )
    copy.enabled = False
    modes.append(copy)
    _persist_modes(request, workspace, modes)
    return copy


def _validate_mode(
    mode: CustomLoopModeConfig,
    workspace: Any,
    other_modes: list[CustomLoopModeConfig],
    ignored_mode: CustomLoopModeConfig | None = None,
) -> None:
    """Validate catalog data and command collisions."""
    try:
        compile_loop_mode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if any(item.slash_command == mode.slash_command for item in other_modes):
        raise HTTPException(status_code=409, detail="Slash command exists")
    normalized_name = mode.name.lower()
    if any(item.name.lower() == normalized_name for item in other_modes):
        raise HTTPException(status_code=409, detail="Mode name exists")
    registered = set(workspace.plugins.slash_command_registry.names())
    if ignored_mode is not None:
        registered.discard(ignored_mode.slash_command)
    if mode.slash_command in registered:
        raise HTTPException(status_code=409, detail="Slash command exists")


def _persist_modes(
    request: Request,
    workspace: Any,
    modes: list[CustomLoopModeConfig],
) -> None:
    """Persist modes and schedule a safe workspace reload."""
    config = workspace.config
    config.running.loop.custom_modes = modes
    save_agent_config(workspace.agent_id, config)
    schedule_agent_reload(request, workspace.agent_id)


def _find_mode(modes: list[CustomLoopModeConfig], mode_id: str) -> int:
    for index, mode in enumerate(modes):
        if mode.id == mode_id:
            return index
    raise HTTPException(status_code=404, detail="Custom mode not found")


def _unique_value(base: str, existing: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _deduplicate(loops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for loop in loops:
        key = str(loop.get("slash_command") or loop["name"])
        if key not in seen:
            seen.add(key)
            result.append(loop)
    return result


def _list_plugin_loops() -> list[dict[str, Any]]:
    """List loops registered by plugins."""
    result: list[dict[str, Any]] = []
    try:
        from ...plugins.registry import PluginRegistry

        manager = PluginRegistry().get_workspace_manager()
        if manager is None:
            return result
        for workspace in getattr(manager, "workspaces", {}).values():
            plugins = getattr(workspace, "plugins", None)
            for registration in getattr(plugins, "stop_handlers", []):
                metadata = getattr(registration, "metadata", {})
                if metadata.get("loop_name"):
                    result.append(
                        {
                            "name": metadata["loop_name"],
                            "slash_command": metadata.get(
                                "slash_command",
                                metadata["loop_name"],
                            ),
                            "description": metadata.get("description", ""),
                            "source": "plugin",
                        },
                    )
    except Exception:
        logger.warning("Failed to list plugin loops", exc_info=True)
    return result


__all__ = ["router"]

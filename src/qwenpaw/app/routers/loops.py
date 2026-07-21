# -*- coding: utf-8 -*-
"""Loop discovery, catalog, and custom mode persistence APIs."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from ...config.config import (
    CustomLoopModeConfig,
    normalize_custom_loop_mode_name,
    save_agent_config,
)
from ...loop.catalog import get_gate_catalog
from ...loop.compiler import compile_loop_mode
from ...utils.logging import sanitize_log_value
from ..agent_context import get_agent_for_request, scoped_session_id
from ..utils import schedule_agent_reload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/loops", tags=["loops"])


class LoopModeInfo(BaseModel):
    """One loop mode available in the chat composer."""

    id: str
    name: str
    slash_command: str
    description: str
    source: Literal["builtin", "custom", "plugin"]


class LoopModeStatus(BaseModel):
    """Active loop state for one conversation session."""

    state: Literal["idle", "running", "awaiting_user"]
    mode: LoopModeInfo | None = None


BUILTIN_LOOPS = (
    LoopModeInfo(
        id="default",
        name="default",
        slash_command="",
        description="The standard guarded agent loop.",
        source="builtin",
    ),
    LoopModeInfo(
        id="goal",
        name="goal",
        slash_command="goal",
        description="Set a goal and work until it is done.",
        source="builtin",
    ),
    LoopModeInfo(
        id="mission",
        name="mission",
        slash_command="mission",
        description="Run a persistent multi-step mission.",
        source="builtin",
    ),
)


def _session_context_state(
    saved_state: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the agent payload and its persisted mode_state."""
    agent_state = saved_state or {}
    nested_agent = agent_state.get("agent")
    if isinstance(nested_agent, dict):
        agent_state = nested_agent
    mode_state = agent_state.get("mode_state")
    if not isinstance(mode_state, dict):
        mode_state = {}
    return agent_state, mode_state


@router.get("", response_model=list[LoopModeInfo])
async def list_loops(request: Request) -> list[LoopModeInfo]:
    """List built-in, custom, and plugin-provided loops."""
    workspace = await get_agent_for_request(request)
    catalog, _ = _build_loop_catalog(workspace)
    return catalog


@router.get("/status", response_model=LoopModeStatus)
async def get_loop_status(
    request: Request,
    chat_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
) -> LoopModeStatus:
    """Return the explicit loop mode active in one session."""
    workspace = await get_agent_for_request(request)
    session_state: dict[str, Any] | None = None
    execution_phase: Literal["running", "awaiting_user"] = "awaiting_user"
    if chat_id:
        chat = await workspace.chat_manager.get_chat(chat_id)
        if chat is None and not session_id:
            raise HTTPException(status_code=404, detail="Chat not found")
        if chat is not None:
            session_id = chat.session_id
            run_status = await workspace.task_tracker.get_status(chat.id)
            if run_status == "running":
                execution_phase = "running"
            session_state = await workspace.session.get_session_state_dict(
                chat.session_id,
                chat.user_id,
                chat.channel,
            )
    if not session_id:
        return LoopModeStatus(state="idle")

    catalog, runtime_modes = _build_loop_catalog(workspace)
    by_id = {mode.id: mode for mode in catalog}
    agent_state, mode_state = _session_context_state(session_state)
    ctx = SimpleNamespace(
        session_id=session_id,
        session_state=agent_state,
        mode_state=mode_state,
        workspace=workspace,
        agent_config=workspace.config,
        agent=getattr(workspace, "agent", None),
    )
    active: list[LoopModeInfo] = []
    with scoped_session_id(session_id):
        for mode in getattr(workspace.plugins, "modes", []):
            descriptor_id = runtime_modes.get(getattr(mode, "name", ""))
            if descriptor_id is None or descriptor_id == "default":
                continue
            try:
                if mode.is_active(ctx):
                    descriptor = by_id.get(descriptor_id)
                    if descriptor is not None:
                        active.append(descriptor)
            except Exception:
                logger.warning(
                    "Failed to inspect loop mode '%s'",
                    getattr(mode, "name", "?"),
                    exc_info=True,
                )
    if not active:
        return LoopModeStatus(state="idle")
    if len(active) > 1:
        logger.warning(
            "Multiple loop modes active for session '%s': %s",
            sanitize_log_value(session_id),
            [mode.id for mode in active],
        )
    return LoopModeStatus(state=execution_phase, mode=active[0])


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
    await _persist_modes(request, workspace, modes)
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
    await _persist_modes(request, workspace, modes)
    return mode


@router.delete("/custom/{mode_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_mode(request: Request, mode_id: str) -> None:
    """Delete one saved custom mode."""
    workspace = await get_agent_for_request(request)
    modes = list(workspace.config.running.loop.custom_modes)
    index = _find_mode(modes, mode_id)
    modes.pop(index)
    await _persist_modes(request, workspace, modes)


@router.post(
    "/custom/{mode_id}/duplicate",
    response_model=CustomLoopModeConfig,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_custom_mode(
    request: Request,
    mode_id: str,
) -> CustomLoopModeConfig:
    """Create an available copy with unique identity and command."""
    workspace = await get_agent_for_request(request)
    modes = list(workspace.config.running.loop.custom_modes)
    source = modes[_find_mode(modes, mode_id)]
    payload = source.model_dump()
    payload["id"] = _unique_value(
        f"{source.id}-copy",
        {item.id for item in modes},
        max_length=64,
    )
    payload["name"] = _unique_value(
        f"{source.name} Copy",
        {normalize_custom_loop_mode_name(item.name) for item in modes},
        max_length=80,
        normalize=normalize_custom_loop_mode_name,
    )
    payload["slash_command"] = _unique_value(
        f"{source.slash_command}-copy",
        {item.slash_command for item in modes},
        max_length=64,
    )
    payload["enabled"] = any(gate.enabled for gate in source.gates)
    copy = CustomLoopModeConfig.model_validate(payload)
    _validate_mode(copy, workspace, modes)
    modes.append(copy)
    await _persist_modes(request, workspace, modes)
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
    normalized_name = normalize_custom_loop_mode_name(mode.name)
    if any(
        normalize_custom_loop_mode_name(item.name) == normalized_name
        for item in other_modes
    ):
        raise HTTPException(status_code=409, detail="Mode name exists")
    registered = set(workspace.plugins.slash_command_registry.names())
    if ignored_mode is not None:
        registered.discard(ignored_mode.slash_command)
    if mode.slash_command in registered:
        raise HTTPException(status_code=409, detail="Slash command exists")


async def _persist_modes(
    request: Request,
    workspace: Any,
    modes: list[CustomLoopModeConfig],
) -> None:
    """Persist modes and schedule a safe workspace reload."""
    config = workspace.config
    config.running.loop.custom_modes = modes
    await asyncio.to_thread(save_agent_config, workspace.agent_id, config)
    schedule_agent_reload(request, workspace.agent_id)


def _find_mode(modes: list[CustomLoopModeConfig], mode_id: str) -> int:
    for index, mode in enumerate(modes):
        if mode.id == mode_id:
            return index
    raise HTTPException(status_code=404, detail="Custom mode not found")


def _unique_value(
    base: str,
    existing: set[str],
    *,
    max_length: int,
    normalize: Callable[[str], str] | None = None,
) -> str:
    normalize_value = normalize or (lambda value: value)
    candidate = base[:max_length]
    suffix = 2
    while normalize_value(candidate) in existing:
        suffix_text = f"-{suffix}"
        candidate = f"{base[: max_length - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return candidate


def _deduplicate(loops: list[LoopModeInfo]) -> list[LoopModeInfo]:
    seen: set[str] = set()
    result: list[LoopModeInfo] = []
    for loop in loops:
        key = loop.slash_command or loop.id
        if key not in seen:
            seen.add(key)
            result.append(loop)
    return result


def _build_loop_catalog(
    workspace: Any,
) -> tuple[list[LoopModeInfo], dict[str, str]]:
    """Build one workspace's catalog and runtime-name lookup."""
    result = list(BUILTIN_LOOPS)
    runtime_modes = {
        "default": "default",
        "goal": "goal",
        "mission": "mission",
    }
    for mode in workspace.config.running.loop.custom_modes:
        if not mode.enabled:
            continue
        descriptor_id = f"custom:{mode.id}"
        result.append(
            LoopModeInfo(
                id=descriptor_id,
                name=mode.name,
                slash_command=mode.slash_command,
                description=mode.description,
                source="custom",
            ),
        )
        runtime_modes[descriptor_id] = descriptor_id

    builtin_names = {"default", "goal", "mission"}
    for mode in getattr(workspace.plugins, "modes", []):
        runtime_name = getattr(mode, "name", "")
        if (
            not runtime_name
            or runtime_name in builtin_names
            or runtime_name.startswith("custom:")
            or runtime_name == "custom-loop-control"
        ):
            continue
        try:
            commands = mode.commands()
        except Exception:
            logger.warning(
                "Failed to inspect plugin loop mode '%s'",
                runtime_name,
                exc_info=True,
            )
            continue
        if not commands:
            continue
        command = commands[0]
        metadata = command.metadata or {}
        descriptor_id = f"plugin:{runtime_name}"
        result.append(
            LoopModeInfo(
                id=descriptor_id,
                name=str(metadata.get("loop_name") or runtime_name),
                slash_command=command.name,
                description=command.help_text,
                source="plugin",
            ),
        )
        runtime_modes[runtime_name] = descriptor_id
    return _deduplicate(result), runtime_modes


__all__ = ["LoopModeInfo", "LoopModeStatus", "router"]

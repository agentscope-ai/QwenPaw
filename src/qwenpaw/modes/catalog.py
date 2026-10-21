# -*- coding: utf-8 -*-
"""Shared loop mode discovery for HTTP, console, and ACP entry points."""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LoopModeInfo(BaseModel):
    """One loop mode available in the chat composer."""

    id: str
    name: str
    slash_command: str
    description: str
    source: Literal["builtin", "custom", "plugin"]
    name_i18n: dict[str, str] | None = None
    description_i18n: dict[str, str] | None = None


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


ADVISOR_LOOP = LoopModeInfo(
    id="advisor",
    name="advisor",
    slash_command="advisor",
    description=(
        "Let a stronger model plan and step in while a cheaper one does "
        "the work."
    ),
    source="builtin",
)


def _deduplicate(loops: list[LoopModeInfo]) -> list[LoopModeInfo]:
    seen: set[str] = set()
    result: list[LoopModeInfo] = []
    for loop in loops:
        key = loop.slash_command or loop.id
        if key not in seen:
            seen.add(key)
            result.append(loop)
    return result


def build_loop_catalog(
    workspace: Any,
) -> tuple[list[LoopModeInfo], dict[str, str]]:
    """Build one workspace's catalog and runtime-name lookup."""
    result = list(BUILTIN_LOOPS)
    runtime_modes = {
        "default": "default",
        "goal": "goal",
        "mission": "mission",
    }
    # Advisor is bundled like goal and mission but only offered once it is
    # switched on for the agent.
    advisor_mode = getattr(workspace.config, "advisor_mode", None)
    if getattr(advisor_mode, "enabled", False) is True:
        result.append(ADVISOR_LOOP)
        runtime_modes["advisor"] = "advisor"
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

    builtin_names = {"default", "goal", "mission", "advisor"}
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
        name_i18n = _as_str_dict(metadata.get("name_i18n"))
        description_i18n = _as_str_dict(metadata.get("description_i18n"))
        result.append(
            LoopModeInfo(
                id=descriptor_id,
                name=str(metadata.get("loop_name") or runtime_name),
                slash_command=command.name,
                description=command.help_text,
                source="plugin",
                name_i18n=name_i18n or None,
                description_i18n=description_i18n or None,
            ),
        )
        runtime_modes[runtime_name] = descriptor_id
    return _deduplicate(result), runtime_modes


def _as_str_dict(value: Any) -> dict[str, str]:
    """Normalize metadata i18n maps to ``dict[str, str]``."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        if item is None:
            continue
        text = str(item).strip()
        if text:
            result[str(key)] = text
    return result


def resolve_loop_mode(workspace: Any, mode_id: str) -> LoopModeInfo:
    """Resolve a selectable mode and verify its activation command exists."""
    catalog, _ = build_loop_catalog(workspace)
    mode = next((item for item in catalog if item.id == mode_id), None)
    if mode is None:
        available = ", ".join(item.id for item in catalog)
        raise ValueError(
            f"Unknown loop mode '{mode_id}'. Available: {available}",
        )
    if mode.slash_command:
        registry = workspace.plugins.slash_command_registry
        if registry.resolve(f"/{mode.slash_command}") is None:
            raise ValueError(f"Loop mode '{mode_id}' is not registered")
    return mode

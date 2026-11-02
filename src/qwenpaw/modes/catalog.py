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


def build_loop_catalog(
    workspace: Any,
) -> tuple[list[LoopModeInfo], dict[str, str]]:
    """Collect selectable modes from registered workspace instances."""
    result: list[LoopModeInfo] = []
    runtime_modes: dict[str, str] = {}
    seen: set[str] = set()
    registry = workspace.plugins.slash_command_registry
    for mode in workspace.plugins.modes:
        try:
            descriptor = mode.describe_loop(workspace)
        except Exception:
            logger.warning(
                f"Failed to describe loop mode '{mode.name}'",
                exc_info=True,
            )
            continue
        if descriptor is None:
            continue
        command = descriptor.slash_command
        if command and registry.resolve(f"/{command}") is None:
            continue
        key = command or descriptor.id
        if key in seen:
            continue
        seen.add(key)
        result.append(descriptor)
        runtime_modes[mode.name] = descriptor.id
    return result, runtime_modes


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
    return mode

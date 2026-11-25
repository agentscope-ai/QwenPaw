# -*- coding: utf-8 -*-
"""Shared loop mode discovery for HTTP, console, and ACP entry points."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from ..runtime.message_convert import rewrite_user_msg

if TYPE_CHECKING:
    from agentscope.message import Msg

    from ..runtime.hooks import HookContext
    from .base import AgentMode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModeActivation:
    """Native mode entry shared by every transport."""

    id: str
    command: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    def prepare_message(self, text: str) -> str:
        """Enter command-driven modes without changing explicit commands."""
        if not self.command or text.lstrip().startswith("/"):
            return text
        return f"/{self.command} {text}"


@dataclass(frozen=True)
class ModeEntry:
    """Track whether a session should retry its automatic mode command."""

    mode_id: str
    retry: bool = False


def _resolve_mode(
    workspace: Any,
    mode_id: str,
) -> tuple[AgentMode, ModeActivation]:
    for mode in workspace.plugins.modes:
        activation = mode.describe_activation(workspace)
        if activation is not None and activation.id == mode_id:
            command = activation.command
            if (
                command
                and workspace.plugins.slash_command_registry.resolve(
                    f"/{command}",
                )
                is None
            ):
                break
            return mode, activation
    raise ValueError(f"Unknown or unavailable agent mode: {mode_id!r}")


def resolve_mode_activation(workspace: Any, mode_id: str) -> ModeActivation:
    """Resolve mode-owned configuration and its optional entry command."""
    return _resolve_mode(workspace, mode_id)[1]


async def dispatch_session_command(ctx: HookContext, text: str) -> Msg | None:
    """Apply automatic mode entry once, retrying failed automatic attempts."""
    plugins = ctx.workspace.plugins
    dispatch = plugins.slash_command_registry.dispatch
    mode_id = ctx.agent_config.agent_mode
    session_id = ctx.session_id
    entries = plugins.session_modes
    if mode_id is None:
        entries.pop(session_id, None)
        return await dispatch(text, ctx)
    handled = ModeEntry(mode_id)
    previous = entries.get(session_id)
    if previous == handled:
        return await dispatch(text, ctx)

    mode, activation = _resolve_mode(ctx.workspace, mode_id)
    restored = previous is None and mode_id == ctx.parameters.restored_mode
    if restored or not activation.command or mode.is_active(ctx):
        entries[session_id] = handled
        return await dispatch(text, ctx)

    retry = ModeEntry(mode_id, retry=True)
    prepared = activation.prepare_message(text)
    if prepared == text:
        if previous != retry:
            entries[session_id] = handled
        return await dispatch(text, ctx)
    rewrite_user_msg(ctx, prepared, preserve_non_text=True)
    entries[session_id] = retry
    result = await dispatch(prepared, ctx)
    if mode.is_active(ctx):
        entries[session_id] = handled
    return result


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

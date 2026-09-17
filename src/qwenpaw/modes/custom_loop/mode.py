# -*- coding: utf-8 -*-
"""Runtime modes compiled from saved gate pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from agentscope.message import Msg, TextBlock

from ...app.agent_context import get_current_session_id
from ...config.config import CustomLoopModeConfig
from ...loop.compiler import compile_loop_mode
from ...loop.gates import StopHandler, StopHandlerRegistration
from ...runtime.hooks import HookContext
from ...runtime.slash_command_registry import CommandSpec
from ..base import AgentMode
from ..base import find_active_explicit_mode


def _system_message(text: str) -> Msg:
    """Build a small command response."""
    return Msg(
        name="system",
        role="system",
        content=[TextBlock(type="text", text=text)],
    )


def _rewrite_user_message(ctx: HookContext, text: str) -> None:
    """Replace the dispatched slash command with its task text."""
    if not ctx.input_msgs:
        return
    message = ctx.input_msgs[-1]
    if isinstance(message, Msg):
        message.content = [TextBlock(type="text", text=text)]


def _reset_mode_handler(ctx: HookContext, mode_id: str) -> None:
    """Reset one custom mode handler in the current session."""
    target_name = f"custom:{mode_id}"
    for mode in ctx.workspace.plugins.modes:
        if getattr(mode, "name", "") == target_name:
            mode.handler.reset_session()
            return


@dataclass
class LoopModeActivationStore:
    """Per-workspace active custom mode IDs keyed by session."""

    active_modes: dict[str, str] = field(default_factory=dict)

    def activate(self, session_id: str, mode_id: str) -> str | None:
        """Activate a mode and return the previous mode ID."""
        previous = self.active_modes.get(session_id)
        self.active_modes[session_id] = mode_id
        return previous

    def deactivate(self, session_id: str) -> str | None:
        """Deactivate and return the previous mode ID."""
        return self.active_modes.pop(session_id, None)

    def current(self, session_id: str) -> str | None:
        """Return the active mode ID for a session."""
        return self.active_modes.get(session_id)


class DeclarativeLoopMode(AgentMode):
    """One saved custom gate pipeline."""

    def __init__(
        self,
        config: CustomLoopModeConfig,
        activation_store: LoopModeActivationStore,
    ) -> None:
        self.config = config
        self.name = f"custom:{config.id}"
        self._activation_store = activation_store
        self._handler: StopHandler = compile_loop_mode(config)

    @property
    def handler(self) -> StopHandler:
        """Expose the mode-owned handler for tests and introspection."""
        return self._handler

    def commands(self) -> list[CommandSpec]:
        """Expose the configured slash command."""
        return [
            CommandSpec(
                name=self.config.slash_command,
                handler=self._activate_handler,
                category="custom_loop",
                help_text=self.config.description,
                metadata={
                    "loop_name": self.config.name,
                    "custom_loop": True,
                },
            ),
        ]

    def setup(self, workspace: object) -> None:
        """Register command and custom-scoped handler."""
        super().setup(workspace)
        workspace.plugins.stop_handlers.append(
            StopHandlerRegistration(
                plugin_id="__custom_loop_mode__",
                handler=self._handler,
                priority=0,
                name=f"custom-loop-{self.config.id}",
                scope=f"custom:{self.config.id}",
                is_active=self._is_current_session_active,
            ),
        )

    def is_active(self, ctx: HookContext) -> bool:
        """Return whether this mode owns the current session."""
        return self._activation_store.current(ctx.session_id) == self.config.id

    async def on_turn_start(self, ctx: HookContext) -> None:
        """Reset gates only when this mode is active."""
        if self.is_active(ctx):
            self._handler.reset_turn()

    async def on_conversation_reset(self, ctx: HookContext) -> None:
        """Clear this mode's current-session state."""
        self._handler.reset_session()

    def _is_current_session_active(self) -> bool:
        session_id = get_current_session_id() or "default"
        return self._activation_store.current(session_id) == self.config.id

    async def _activate_handler(
        self,
        ctx: HookContext,
        args: str,
    ) -> Msg | None:
        """Activate this custom mode for the current conversation."""
        conflict = find_active_explicit_mode(ctx)
        if conflict is not None:
            return _system_message(
                f"End the active {conflict} mode before switching to "
                f"/{self.config.slash_command}.",
            )

        previous = self._activation_store.activate(
            ctx.session_id,
            self.config.id,
        )
        if previous and previous != self.config.id:
            _reset_mode_handler(ctx, previous)

        task = args.strip()
        if not task:
            return _system_message(
                f"Custom loop mode '{self.config.name}' is active.",
            )
        _rewrite_user_message(ctx, task)
        return None


class CustomLoopController(AgentMode):
    """Own the shared /mode off command and activation cleanup."""

    name = "custom-loop-control"

    def __init__(self, activation_store: LoopModeActivationStore) -> None:
        self._activation_store = activation_store

    def commands(self) -> list[CommandSpec]:
        """Expose the shared custom loop control command."""
        return [
            CommandSpec(
                name="mode",
                handler=self._mode_handler,
                category="custom_loop",
                help_text="Disable the active custom loop mode.",
            ),
        ]

    async def on_conversation_reset(self, ctx: HookContext) -> None:
        """Clear current custom activation on conversation reset."""
        self._activation_store.deactivate(ctx.session_id)

    async def _mode_handler(
        self,
        ctx: HookContext,
        args: str,
    ) -> Msg:
        """Handle /mode off and report invalid usage."""
        if args.strip().lower() != "off":
            return _system_message("Usage: /mode off")
        previous = self._activation_store.deactivate(ctx.session_id)
        if previous is None:
            return _system_message("No custom loop mode is active.")
        _reset_mode_handler(ctx, previous)
        return _system_message("Custom loop mode disabled.")


__all__ = [
    "CustomLoopController",
    "DeclarativeLoopMode",
    "LoopModeActivationStore",
]

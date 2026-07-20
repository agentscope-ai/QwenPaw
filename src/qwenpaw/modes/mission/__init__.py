# -*- coding: utf-8 -*-
"""Mission mode — ``AgentMode`` for autonomous iterative tasks.

Exposes hooks and a prompt contributor so the Runtime
lifecycle drives mission state load/save.  All domain
logic (command handler, state files, prompts, gate)
lives under ``modes.mission``.

The Phase 2 execution loop is driven by ``MissionGate``
registered into the universal ``StopHandler``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from agentscope.message import Msg, TextBlock

from ..base import AgentMode
from ...runtime.hooks import HookBase, HookContext
from ...runtime.slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from typing import Any

    from .gates import MissionGate

logger = logging.getLogger(__name__)


class MissionMode(AgentMode):
    """Bundle for mission-mode behaviour."""

    name = "mission"

    def __init__(self) -> None:
        self._gate: MissionGate | None = None

    # ── commands ──

    def commands(self) -> list[CommandSpec]:
        """Register ``/mission`` as a standard command."""
        from .handler import (
            MISSION_HELP_TEXT,
        )

        return [
            CommandSpec(
                name="mission",
                handler=self._mission_handler,
                category="builtin",
                help_text=MISSION_HELP_TEXT,
                metadata={"builtin": True},
            ),
        ]

    # ── hooks / contributors ──

    def hooks(self) -> list[HookBase]:
        from .hooks import (
            MissionStateLoadHook,
            MissionStateSaveHook,
        )

        return [
            MissionStateLoadHook(owner_mode=self),
            MissionStateSaveHook(owner_mode=self),
        ]

    def prompt_contributors(self) -> list:
        from .contributor import MissionPromptContributor

        return [
            MissionPromptContributor(owner_mode=self),
        ]

    # ── setup ──

    def setup(self, workspace: object) -> None:
        """Register MissionGate in a separate handler."""
        super().setup(workspace)

        from .gates import MissionGate as _MG
        from ...loop.gates import (
            StopHandler,
            StopHandlerRegistration,
        )

        handler = StopHandler()
        gate = _MG()
        handler.register(gate)
        self._gate = gate

        plugins = getattr(workspace, "plugins", None)
        if plugins is not None:
            if not hasattr(plugins, "stop_handlers"):
                plugins.stop_handlers = []
            plugins.stop_handlers.append(
                StopHandlerRegistration(
                    plugin_id="__mission__",
                    handler=handler,
                    priority=0,
                    name="mission-stop-handler",
                    scope="mission",
                    is_active=self._is_gate_active,
                ),
            )

    async def on_turn_start(self, ctx: HookContext) -> None:
        """Restore persisted mission state before handler scope selection."""
        if self._gate is not None:
            await asyncio.to_thread(self._gate.restore, ctx)

    def on_conversation_reset(
        self,
        ctx: HookContext,  # noqa: ARG002
    ) -> None:
        """Clear active mission gate state."""
        if self._gate is not None:
            self._gate.reset_session()

    def is_active(self, ctx: HookContext) -> bool:
        return self._is_gate_active() or bool(
            (ctx.session_state or {}).get(
                "mission_active",
            ),
        )

    # ── command handler ──

    async def _mission_handler(
        self,
        ctx: "Any",
        args: str,
    ) -> Optional[Msg]:
        """Handle ``/mission [args]``.

        Returns ``Msg`` for info sub-commands (status,
        list, help) and ``None`` for new-mission starts
        so the agent processes the rewritten message.
        """
        from .handler import (
            format_help,
            format_list,
            format_status,
            parse_mission_args,
            start_mission,
        )

        parsed = parse_mission_args(args or "")
        task_text = parsed["task_text"]

        # --- info sub-commands ---
        if task_text.strip().lower() == "status":
            workspace_dir = getattr(ctx, "workspace_dir")
            session_id = getattr(
                ctx,
                "session_id",
                "",
            )
            text = format_status(
                workspace_dir,
                session_id,
            )
            return _info_msg(text)

        if task_text.strip().lower() == "list":
            workspace_dir = getattr(ctx, "workspace_dir")
            text = format_list(workspace_dir)
            return _info_msg(text)

        # --- help / empty ---
        if not task_text or len(task_text.strip()) < 5:
            return _info_msg(format_help())

        # --- start new mission ---
        workspace_dir = getattr(ctx, "workspace_dir")
        agent_id = getattr(ctx, "agent_id", "")
        session_id = getattr(ctx, "session_id", "")

        prompt, loop_dir = await start_mission(
            task_text=task_text,
            workspace_dir=workspace_dir,
            agent_id=agent_id,
            session_id=session_id,
            verify_commands=parsed["verify_commands"],
            max_iterations=parsed["max_iterations"],
        )

        if self._gate is not None:
            self._gate.activate_for_mission(loop_dir)

        _rewrite_user_msg(ctx, prompt)
        logger.info(
            f"Mission started session={session_id}" f" loop_dir={loop_dir}",
        )
        return None

    def _is_gate_active(self) -> bool:
        """Check if MissionGate has active state."""
        if self._gate is None:
            return False
        # pylint: disable=protected-access
        return self._gate._state() is not None


def _info_msg(text: str) -> Msg:
    """Wrap text into a system Msg for display."""
    return Msg(
        name="system",
        content=[TextBlock(type="text", text=text)],
        role="system",
    )


def _rewrite_user_msg(ctx: "Any", text: str) -> None:
    """Replace the last user message with *text*."""
    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return
    last = msgs[-1]
    if not isinstance(last, Msg):
        return
    last.content = [TextBlock(type="text", text=text)]


__all__ = ["MissionMode"]

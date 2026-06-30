# -*- coding: utf-8 -*-
"""Autopilot — Autonomous Execution Loop plugin."""
from __future__ import annotations

from pathlib import Path

from qwenpaw.loop.gates import LoopGate


class AutopilotGate(LoopGate):
    """Continue until max iterations or budget hit."""

    _MAX_ITERATIONS = 50

    @property
    def name(self) -> str:
        return "autopilot"

    @property
    def priority(self) -> int:
        return 100

    def _is_complete(
        self,
        state_dir: Path,  # pylint: disable=unused-argument
    ) -> bool:
        return False

    def continuation_prompt(self) -> str:
        return (
            "Continue working autonomously. " "Complete the task step by step."
        )


class AutopilotPlugin:
    """Plugin entry point."""

    def register(self, api) -> None:
        """Register autopilot loop plugin."""
        gate = AutopilotGate()

        async def _activate(_ctx, args: str):
            from agentscope.message import Msg

            gate.activate()
            return Msg(
                name="system",
                content=(f"Autopilot mode activated. " f"Task: {args}"),
                role="system",
            )

        api.register_slash_command(
            name="autopilot",
            handler=_activate,
            help_text=(
                "Autonomous execution loop — "
                "free execution with budget control."
            ),
        )
        api.register_agent_stop_handler(
            handler=gate.check,
            priority=gate.priority,
            name=gate.name,
        )


plugin = AutopilotPlugin()

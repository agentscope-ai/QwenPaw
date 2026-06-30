# -*- coding: utf-8 -*-
"""Deep Interview — Multi-round Interview Loop plugin."""
from __future__ import annotations

import json
from pathlib import Path

from qwenpaw.loop.gates import LoopGate


class DeepInterviewGate(LoopGate):
    """Continue until interview is synthesized."""

    _MAX_ITERATIONS = 20

    @property
    def name(self) -> str:
        return "deep-interview"

    @property
    def priority(self) -> int:
        return 95

    def _is_complete(self, state_dir: Path) -> bool:
        state_path = state_dir / "interview-state.json"
        if not state_path.exists():
            return False
        try:
            data = json.loads(
                state_path.read_text(encoding="utf-8"),
            )
            return data.get("synthesized", False)
        except Exception:
            return False

    def continuation_prompt(self) -> str:
        return (
            "Continue the interview. Ask the next "
            "question or synthesize findings if all "
            "questions have been answered."
        )


class DeepInterviewPlugin:
    """Plugin entry point."""

    def register(self, api) -> None:
        """Register deep-interview loop plugin."""
        gate = DeepInterviewGate()

        async def _activate(ctx, args: str):
            from agentscope.message import Msg

            gate.activate(
                Path(ctx.get("workspace_dir", ".")),
            )
            return Msg(
                name="system",
                content=(f"Deep interview activated. " f"Topic: {args}"),
                role="system",
            )

        api.register_slash_command(
            name="interview",
            handler=_activate,
            help_text=("Deep interview loop — " "multi-round questioning."),
        )
        api.register_agent_stop_handler(
            handler=gate.check,
            priority=gate.priority,
            name=gate.name,
        )


plugin = DeepInterviewPlugin()

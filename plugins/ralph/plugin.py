# -*- coding: utf-8 -*-
"""Ralph — Persistent Completion Loop plugin."""
from __future__ import annotations

import json
from pathlib import Path

from qwenpaw.loop.gates import LoopGate


class RalphGate(LoopGate):
    """Continue until all stories are done."""

    _MAX_ITERATIONS = 30

    @property
    def name(self) -> str:
        return "ralph"

    def _is_complete(self, state_dir: Path) -> bool:
        state_path = state_dir / "ralph-state.json"
        if not state_path.exists():
            return False
        try:
            data = json.loads(
                state_path.read_text(encoding="utf-8"),
            )
            stories = data.get("stories", [])
            if not stories:
                return False
            return all(
                s.get("status") == "done" and s.get("verified")
                for s in stories
            )
        except Exception:
            return False

    def continuation_prompt(self) -> str:
        return (
            "There are still unfinished stories. "
            "Check ralph-state.json and continue "
            "working on the next pending story."
        )


class RalphPlugin:
    """Plugin entry point."""

    def register(self, api) -> None:
        """Register ralph loop plugin."""
        gate = RalphGate()

        async def _activate(ctx, args: str):
            from agentscope.message import Msg

            gate.activate(
                Path(ctx.get("workspace_dir", ".")),
            )
            return Msg(
                name="system",
                content=(f"Ralph loop activated. " f"Task: {args}"),
                role="system",
            )

        api.register_slash_command(
            name="ralph",
            handler=_activate,
            help_text=(
                "Persistent completion loop — " "decompose, execute, verify."
            ),
        )
        api.register_agent_stop_handler(
            handler=gate.check,
            priority=gate.priority,
            name=gate.name,
        )


plugin = RalphPlugin()

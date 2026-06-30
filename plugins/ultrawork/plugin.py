# -*- coding: utf-8 -*-
"""Ultrawork — Parallel Todo Loop plugin."""
from __future__ import annotations

import json
from pathlib import Path

from qwenpaw.loop.gates import FileLoopGate

_PLUGIN_DIR = Path(__file__).parent


class UltraworkGate(FileLoopGate):
    """Continue until all todos are done."""

    _MAX_ITERATIONS = 25

    @property
    def name(self) -> str:
        return "ultrawork"

    @property
    def priority(self) -> int:
        return 95

    def _is_complete(self, state_dir: Path) -> bool:
        state_path = state_dir / "ultrawork-state.json"
        if not state_path.exists():
            return False
        try:
            data = json.loads(
                state_path.read_text(encoding="utf-8"),
            )
            todos = data.get("todos", [])
            if not todos:
                return False
            return all(t.get("done") for t in todos)
        except Exception:
            return False

    def continuation_prompt(self) -> str:
        return (
            "There are still incomplete todos. "
            "Check ultrawork-state.json and "
            "continue with the next item."
        )


class UltraworkPlugin:
    """Plugin entry point."""

    def register(self, api) -> None:
        """Register ultrawork loop plugin."""
        gate = UltraworkGate()

        async def _activate(ctx, args: str):
            from agentscope.message import Msg

            gate.activate(
                Path(ctx.get("workspace_dir", ".")),
            )
            return Msg(
                name="system",
                content=(f"Ultrawork loop activated. Task: {args}"),
                role="system",
            )

        api.register_slash_command(
            name="ultrawork",
            handler=_activate,
            help_text=(
                "Parallel delegation loop — " "decompose todos and complete."
            ),
        )
        api.register_agent_stop_handler(
            handler=gate.check,
            priority=gate.priority,
            name=gate.name,
        )
        api.register_skill_provider(
            skills_dir=_PLUGIN_DIR / "skills",
        )


plugin = UltraworkPlugin()

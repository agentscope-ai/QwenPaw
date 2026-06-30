# -*- coding: utf-8 -*-
"""Browser Mission — Multi-step Web Automation plugin."""
from __future__ import annotations

import json
from pathlib import Path

from qwenpaw.loop.gates import LoopGate


class BrowserMissionGate(LoopGate):
    """Continue until all browser steps are done."""

    _MAX_ITERATIONS = 30

    @property
    def name(self) -> str:
        return "browser-mission"

    @property
    def priority(self) -> int:
        return 85

    def _is_complete(self, state_dir: Path) -> bool:
        path = state_dir / "browser-mission-state.json"
        if not path.exists():
            return False
        try:
            data = json.loads(
                path.read_text(encoding="utf-8"),
            )
            steps = data.get("steps", [])
            if not steps:
                return False
            return all(s.get("status") == "done" for s in steps)
        except Exception:
            return False

    def continuation_prompt(self) -> str:
        return (
            "Continue the browser mission. "
            "Execute the next automation step."
        )


class BrowserMissionPlugin:
    """Plugin entry point."""

    def register(self, api) -> None:
        """Register browser-mission loop plugin."""
        gate = BrowserMissionGate()

        async def _activate(ctx, args: str):
            from agentscope.message import Msg

            gate.activate(
                Path(ctx.get("workspace_dir", ".")),
            )
            return Msg(
                name="system",
                content=(f"Browser mission activated. " f"Mission: {args}"),
                role="system",
            )

        api.register_slash_command(
            name="browser-mission",
            handler=_activate,
            help_text=("Browser automation loop — " "multi-step web tasks."),
        )
        api.register_agent_stop_handler(
            handler=gate.check,
            priority=gate.priority,
            name=gate.name,
        )


plugin = BrowserMissionPlugin()

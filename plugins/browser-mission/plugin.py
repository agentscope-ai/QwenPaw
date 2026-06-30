# -*- coding: utf-8 -*-
"""Browser Mission — Multi-step Web Automation Loop plugin.

Registers a StopGate that keeps the agent executing
browser automation steps until the mission is complete.
"""
from pathlib import Path

from qwenpaw.loop.gates import (
    StopAction,
    StopGate,
    StopHandlerResult,
)


class BrowserMissionGate(StopGate):
    """Gate: continue until browser mission is done."""

    _MAX_ITERATIONS = 30
    _STATE_FILE = ".qwenpaw/loop_state/browser-mission-state.json"

    def __init__(self) -> None:
        self._iteration = 0
        self._active = False
        self._workspace_dir: Path | None = None

    @property
    def name(self) -> str:
        return "browser-mission"

    @property
    def priority(self) -> int:
        return 85

    def activate(self, workspace_dir: Path) -> None:
        """Activate the browser mission loop."""
        self._active = True
        self._iteration = 0
        self._workspace_dir = workspace_dir

    def deactivate(self) -> None:
        """Deactivate the browser mission loop."""
        self._active = False

    async def check(self, ctx) -> StopHandlerResult:
        """Check if browser mission is done."""
        if not self._active:
            return StopHandlerResult(action=StopAction.STOP)

        self._iteration += 1
        if self._iteration > self._MAX_ITERATIONS:
            self._active = False
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=("Browser mission max iterations reached"),
            )

        if self._check_mission_done():
            self._active = False
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Browser mission completed",
            )

        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self.continuation_prompt(),
            reason=(
                f"Browser mission iteration "
                f"{self._iteration}/{self._MAX_ITERATIONS}"
            ),
        )

    def continuation_prompt(self) -> str:
        """Prompt injected to continue the mission."""
        return (
            "Continue the browser mission. Execute the "
            "next step in the automation sequence."
        )

    def _check_mission_done(self) -> bool:
        """Read state file and check completion."""
        if self._workspace_dir is None:
            return False
        state_path = self._workspace_dir / self._STATE_FILE
        if not state_path.exists():
            return False
        try:
            import json

            data = json.loads(
                state_path.read_text(encoding="utf-8"),
            )
            steps = data.get("steps", [])
            if not steps:
                return False
            return all(s.get("status") == "done" for s in steps)
        except Exception:
            return False


class BrowserMissionPlugin:
    """Plugin entry point for browser-mission loop."""

    def register(self, api) -> None:
        """Register browser-mission plugin via PluginApi."""
        gate = BrowserMissionGate()

        async def _activate_handler(ctx, args: str):
            from agentscope.message import Msg

            ws_dir = Path(ctx.get("workspace_dir", "."))
            gate.activate(ws_dir)
            return Msg(
                name="system",
                content=(
                    f"Browser mission loop activated. " f"Mission: {args}"
                ),
                role="system",
            )

        api.register_slash_command(
            name="browser-mission",
            handler=_activate_handler,
            help_text=(
                "Browser automation loop — multi-step "
                "web tasks with doom loop detection."
            ),
        )

        api.register_agent_stop_handler(
            handler=gate.check,
            priority=gate.priority,
            name=gate.name,
        )


plugin = BrowserMissionPlugin()

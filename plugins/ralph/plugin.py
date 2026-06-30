# -*- coding: utf-8 -*-
"""Ralph — Persistent Completion Loop plugin.

Registers a StopGate that keeps the agent looping until
all stories in ralph-state.json are done and verified.
"""
from pathlib import Path

from qwenpaw.loop.gates import (
    StopAction,
    StopGate,
    StopHandlerResult,
)


class RalphGate(StopGate):
    """Gate: continue until all stories are completed."""

    _MAX_ITERATIONS = 30
    _STATE_FILE = ".qwenpaw/loop_state/ralph-state.json"

    def __init__(self) -> None:
        self._iteration = 0
        self._active = False
        self._workspace_dir: Path | None = None

    @property
    def name(self) -> str:
        return "ralph"

    @property
    def priority(self) -> int:
        return 90

    def activate(self, workspace_dir: Path) -> None:
        """Activate the ralph loop."""
        self._active = True
        self._iteration = 0
        self._workspace_dir = workspace_dir

    def deactivate(self) -> None:
        """Deactivate the ralph loop."""
        self._active = False

    async def check(self, ctx) -> StopHandlerResult:
        """Check if all stories are done."""
        if not self._active:
            return StopHandlerResult(action=StopAction.STOP)

        self._iteration += 1
        if self._iteration > self._MAX_ITERATIONS:
            self._active = False
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Ralph max iterations reached",
            )

        if self._check_all_done():
            self._active = False
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="All stories completed",
            )

        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self.continuation_prompt(),
            reason=(
                f"Ralph iteration {self._iteration}" f"/{self._MAX_ITERATIONS}"
            ),
        )

    def continuation_prompt(self) -> str:
        """Prompt injected to continue the loop."""
        return (
            "There are still unfinished stories. "
            "Check ralph-state.json and continue "
            "working on the next pending story."
        )

    def _check_all_done(self) -> bool:
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
            stories = data.get("stories", [])
            if not stories:
                return False
            return all(
                s.get("status") == "done" and s.get("verified")
                for s in stories
            )
        except Exception:
            return False


class RalphPlugin:
    """Plugin entry point for ralph loop."""

    def register(self, api) -> None:
        """Register ralph loop plugin via PluginApi."""
        gate = RalphGate()

        async def _activate_handler(ctx, args: str):
            from agentscope.message import Msg

            ws_dir = Path(ctx.get("workspace_dir", "."))
            gate.activate(ws_dir)
            return Msg(
                name="system",
                content=(f"Ralph loop activated. Task: {args}"),
                role="system",
            )

        api.register_slash_command(
            name="ralph",
            handler=_activate_handler,
            help_text=(
                "Persistent completion loop — "
                "decompose, execute, verify each story."
            ),
        )

        api.register_agent_stop_handler(
            handler=gate.check,
            priority=gate.priority,
            name=gate.name,
        )


plugin = RalphPlugin()

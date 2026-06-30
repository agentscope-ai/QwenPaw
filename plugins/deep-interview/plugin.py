# -*- coding: utf-8 -*-
"""Deep Interview — Multi-round Interview Loop plugin.

Registers a StopGate that keeps the agent interviewing
until all questions are answered and synthesized.
"""
from pathlib import Path

from qwenpaw.loop.gates import (
    StopAction,
    StopGate,
    StopHandlerResult,
)


class DeepInterviewGate(StopGate):
    """Gate: continue until interview is complete."""

    _MAX_ITERATIONS = 20
    _STATE_FILE = ".qwenpaw/loop_state/interview-state.json"

    def __init__(self) -> None:
        self._iteration = 0
        self._active = False
        self._workspace_dir: Path | None = None

    @property
    def name(self) -> str:
        return "deep-interview"

    @property
    def priority(self) -> int:
        return 95

    def activate(self, workspace_dir: Path) -> None:
        """Activate the interview loop."""
        self._active = True
        self._iteration = 0
        self._workspace_dir = workspace_dir

    def deactivate(self) -> None:
        """Deactivate the interview loop."""
        self._active = False

    async def check(self, ctx) -> StopHandlerResult:
        """Check if interview is complete."""
        if not self._active:
            return StopHandlerResult(action=StopAction.STOP)

        self._iteration += 1
        if self._iteration > self._MAX_ITERATIONS:
            self._active = False
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Interview max iterations reached",
            )

        if self._check_complete():
            self._active = False
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Interview synthesized",
            )

        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self.continuation_prompt(),
            reason=(
                f"Interview iteration {self._iteration}"
                f"/{self._MAX_ITERATIONS}"
            ),
        )

    def continuation_prompt(self) -> str:
        """Prompt injected to continue interviewing."""
        return (
            "Continue the interview. Ask the next "
            "question or synthesize findings if all "
            "questions have been answered."
        )

    def _check_complete(self) -> bool:
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
            return data.get("synthesized", False)
        except Exception:
            return False


class DeepInterviewPlugin:
    """Plugin entry point for deep-interview loop."""

    def register(self, api) -> None:
        """Register deep-interview plugin via PluginApi."""
        gate = DeepInterviewGate()

        async def _activate_handler(ctx, args: str):
            from agentscope.message import Msg

            ws_dir = Path(ctx.get("workspace_dir", "."))
            gate.activate(ws_dir)
            return Msg(
                name="system",
                content=(f"Deep interview loop activated. " f"Topic: {args}"),
                role="system",
            )

        api.register_slash_command(
            name="interview",
            handler=_activate_handler,
            help_text=(
                "Deep interview loop — multi-round "
                "questioning and synthesis."
            ),
        )

        api.register_agent_stop_handler(
            handler=gate.check,
            priority=gate.priority,
            name=gate.name,
        )


plugin = DeepInterviewPlugin()

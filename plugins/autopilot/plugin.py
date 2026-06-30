# -*- coding: utf-8 -*-
"""Autopilot — Autonomous Execution Loop plugin.

Registers a StopGate that keeps the agent freely executing
until the task is complete or budget is exhausted.
"""
from qwenpaw.loop.gates import (
    StopAction,
    StopGate,
    StopHandlerResult,
)


class AutopilotGate(StopGate):
    """Gate: continue until task is done or budget hit."""

    _MAX_ITERATIONS = 50

    def __init__(self) -> None:
        self._iteration = 0
        self._active = False

    @property
    def name(self) -> str:
        return "autopilot"

    @property
    def priority(self) -> int:
        return 100

    def activate(self) -> None:
        """Activate the autopilot loop."""
        self._active = True
        self._iteration = 0

    def deactivate(self) -> None:
        """Deactivate the autopilot loop."""
        self._active = False

    async def check(self, ctx) -> StopHandlerResult:
        """Continue until budget exhausted."""
        if not self._active:
            return StopHandlerResult(action=StopAction.STOP)

        self._iteration += 1
        if self._iteration > self._MAX_ITERATIONS:
            self._active = False
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Autopilot max iterations reached",
            )

        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self.continuation_prompt(),
            reason=(
                f"Autopilot iteration {self._iteration}"
                f"/{self._MAX_ITERATIONS}"
            ),
        )

    def continuation_prompt(self) -> str:
        """Prompt injected to continue autonomous work."""
        return (
            "Continue working autonomously. " "Complete the task step by step."
        )


class AutopilotPlugin:
    """Plugin entry point for autopilot loop."""

    def register(self, api) -> None:
        """Register autopilot loop plugin via PluginApi."""
        gate = AutopilotGate()

        async def _activate_handler(_ctx, args: str):
            from agentscope.message import Msg

            gate.activate()
            return Msg(
                name="system",
                content=(f"Autopilot mode activated. " f"Task: {args}"),
                role="system",
            )

        api.register_slash_command(
            name="autopilot",
            handler=_activate_handler,
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

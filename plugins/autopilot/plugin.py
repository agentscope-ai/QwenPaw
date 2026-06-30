# -*- coding: utf-8 -*-
"""Autopilot — Autonomous Execution Loop plugin.

Registers a StopGate that keeps the agent freely executing
until the task is complete or budget is exhausted.
Session-safe: state is keyed by session_id.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from qwenpaw.loop.gates import (
    StopAction,
    StopGate,
    StopHandlerResult,
)


@dataclass
class _SessionState:
    iteration: int = 0
    active: bool = False


def _session_id() -> str:
    from qwenpaw.app.agent_context import (
        get_current_session_id,
    )

    return get_current_session_id() or "default"


class AutopilotGate(StopGate):
    """Gate: continue until budget exhausted."""

    _MAX_ITERATIONS = 50

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}

    def _get(self, sid: str) -> _SessionState:
        if sid not in self._sessions:
            self._sessions[sid] = _SessionState()
        return self._sessions[sid]

    @property
    def name(self) -> str:
        return "autopilot"

    @property
    def priority(self) -> int:
        return 100

    def activate(self) -> None:
        """Activate for current session."""
        sid = _session_id()
        state = self._get(sid)
        state.active = True
        state.iteration = 0

    def deactivate(self) -> None:
        """Deactivate for current session."""
        sid = _session_id()
        self._sessions.pop(sid, None)

    async def check(  # pylint: disable=unused-argument
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        """Continue until budget exhausted."""
        sid = _session_id()
        state = self._get(sid)

        if not state.active:
            return None

        state.iteration += 1
        if state.iteration > self._MAX_ITERATIONS:
            self._sessions.pop(sid, None)
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Autopilot max iterations reached",
            )

        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self.continuation_prompt(),
            reason=(
                f"Autopilot iteration {state.iteration}"
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

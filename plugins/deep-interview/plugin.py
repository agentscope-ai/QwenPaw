# -*- coding: utf-8 -*-
"""Deep Interview — Multi-round Interview Loop plugin.

Registers a StopGate that keeps the agent interviewing
until all questions are answered and synthesized.
Session-safe: state is keyed by session_id.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
    workspace_dir: Optional[Path] = None


def _session_id() -> str:
    from qwenpaw.app.agent_context import (
        get_current_session_id,
    )

    return get_current_session_id() or "default"


class DeepInterviewGate(StopGate):
    """Gate: continue until interview is complete."""

    _MAX_ITERATIONS = 20
    _STATE_FILE = ".qwenpaw/loop_state/interview-state.json"

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}

    def _get(self, sid: str) -> _SessionState:
        if sid not in self._sessions:
            self._sessions[sid] = _SessionState()
        return self._sessions[sid]

    @property
    def name(self) -> str:
        return "deep-interview"

    @property
    def priority(self) -> int:
        return 95

    def activate(self, workspace_dir: Path) -> None:
        """Activate for current session."""
        sid = _session_id()
        state = self._get(sid)
        state.active = True
        state.iteration = 0
        state.workspace_dir = workspace_dir

    def deactivate(self) -> None:
        """Deactivate for current session."""
        sid = _session_id()
        self._sessions.pop(sid, None)

    async def check(  # pylint: disable=unused-argument
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        """Check if interview is complete."""
        sid = _session_id()
        state = self._get(sid)

        if not state.active:
            return None

        state.iteration += 1
        if state.iteration > self._MAX_ITERATIONS:
            self._sessions.pop(sid, None)
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Interview max iterations reached",
            )

        if self._check_complete(state):
            self._sessions.pop(sid, None)
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Interview synthesized",
            )

        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self.continuation_prompt(),
            reason=(
                f"Interview iteration {state.iteration}"
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

    def _check_complete(
        self,
        state: _SessionState,
    ) -> bool:
        """Read state file and check completion."""
        if state.workspace_dir is None:
            return False
        state_path = state.workspace_dir / self._STATE_FILE
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

            ws_dir = Path(
                ctx.get("workspace_dir", "."),
            )
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

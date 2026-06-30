# -*- coding: utf-8 -*-
"""Ultrawork — Parallel Todo Loop plugin.

Registers a StopGate that keeps the agent working until
all todos in ultrawork-state.json are completed.
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


class UltraworkGate(StopGate):
    """Gate: continue until all todos are done."""

    _MAX_ITERATIONS = 25
    _STATE_FILE = ".qwenpaw/loop_state/ultrawork-state.json"

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}

    def _get(self, sid: str) -> _SessionState:
        if sid not in self._sessions:
            self._sessions[sid] = _SessionState()
        return self._sessions[sid]

    @property
    def name(self) -> str:
        return "ultrawork"

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
        """Check if all todos are done."""
        sid = _session_id()
        state = self._get(sid)

        if not state.active:
            return None

        state.iteration += 1
        if state.iteration > self._MAX_ITERATIONS:
            self._sessions.pop(sid, None)
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Ultrawork max iterations reached",
            )

        if self._check_all_done(state):
            self._sessions.pop(sid, None)
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="All todos completed",
            )

        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self.continuation_prompt(),
            reason=(
                f"Ultrawork iteration {state.iteration}"
                f"/{self._MAX_ITERATIONS}"
            ),
        )

    def continuation_prompt(self) -> str:
        """Prompt injected to continue the loop."""
        return (
            "There are still incomplete todos. "
            "Check ultrawork-state.json and "
            "continue with the next item."
        )

    def _check_all_done(
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
            todos = data.get("todos", [])
            if not todos:
                return False
            return all(t.get("done") for t in todos)
        except Exception:
            return False


class UltraworkPlugin:
    """Plugin entry point for ultrawork loop."""

    def register(self, api) -> None:
        """Register ultrawork loop plugin via PluginApi."""
        gate = UltraworkGate()

        async def _activate_handler(ctx, args: str):
            from agentscope.message import Msg

            ws_dir = Path(
                ctx.get("workspace_dir", "."),
            )
            gate.activate(ws_dir)
            return Msg(
                name="system",
                content=(f"Ultrawork loop activated. " f"Task: {args}"),
                role="system",
            )

        api.register_slash_command(
            name="ultrawork",
            handler=_activate_handler,
            help_text=(
                "Parallel delegation loop — "
                "decompose todos and complete each."
            ),
        )

        api.register_agent_stop_handler(
            handler=gate.check,
            priority=gate.priority,
            name=gate.name,
        )


plugin = UltraworkPlugin()

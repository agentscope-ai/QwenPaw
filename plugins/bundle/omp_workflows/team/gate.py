# -*- coding: utf-8 -*-
"""Team pipeline gate — 5-phase with fix retry limit."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.loop_gate import LoopGate

from ..shared.constants import (
    TEAM_MAX_FIX_ATTEMPTS,
    TEAM_MAX_ITERATIONS,
)
from ..shared.state import WorkflowState
from .prompts import build_continuation as _build_prompt


@dataclass
class _TeamState:
    loop_dir: Path
    workspace_dir: Path
    active: bool = True
    iteration: int = 0
    max_iterations: int = TEAM_MAX_ITERATIONS
    agent_count: int = 3
    agent_role: str = "executor"
    fix_attempts: int = 0
    max_fix_attempts: int = TEAM_MAX_FIX_ATTEMPTS
    phase: str = "plan"


class TeamPipelineGate(LoopGate):
    """Stop gate for the Team multi-agent pipeline."""

    @property
    def name(self) -> str:
        return "team"

    @property
    def priority(self) -> int:
        return 50

    def activate_for_team(
        self,
        workspace_dir: Path,
        agent_count: int = 3,
        agent_role: str = "executor",
    ) -> Path:
        wf = WorkflowState(workspace_dir, "team")
        loop_dir = wf.create_instance()

        handoffs = loop_dir / "handoffs"
        handoffs.mkdir(exist_ok=True)
        results = loop_dir / "results"
        results.mkdir(exist_ok=True)

        state = _TeamState(
            loop_dir=loop_dir,
            workspace_dir=workspace_dir,
            agent_count=agent_count,
            agent_role=agent_role,
        )
        wf.write_state(
            {
                "current_phase": "plan",
                "fix_attempts": 0,
            },
        )
        self.activate(state)
        return loop_dir

    async def check(self, ctx: Any) -> Optional[StopHandlerResult]:
        if isinstance(ctx, dict) and ctx.get("has_tool_calls"):
            return StopHandlerResult(action=StopAction.BYPASS)

        st: _TeamState | None = self._state()
        if st is None:
            return StopHandlerResult(
                action=StopAction.BYPASS,
            )

        wf = WorkflowState.from_existing(
            st.workspace_dir,
            "team",
            st.loop_dir,
        )
        data = await asyncio.to_thread(wf.read_state)

        st.iteration += 1
        if st.iteration > st.max_iterations:
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"Iteration limit ({st.max_iterations})",
            )

        prev_phase = st.phase
        phase = data.get("current_phase", "plan")
        st.phase = phase

        if phase == "completed":
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="Team pipeline completed",
            )

        # Count fix *rounds* (phase entry), not every agent turn.
        if phase == "fix" and prev_phase != "fix":
            st.fix_attempts += 1
            if st.fix_attempts > st.max_fix_attempts:
                await asyncio.to_thread(wf.cleanup)
                self.deactivate()
                return StopHandlerResult(
                    action=StopAction.TERMINATE,
                    reason=f"Fix retry limit ({st.max_fix_attempts})",
                )
            await asyncio.to_thread(
                wf.update_state,
                {"fix_attempts": st.fix_attempts},
            )

        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="Team pipeline in progress",
        )

    def build_continuation(self) -> str:
        """Build Team continuation from gate state."""
        st: _TeamState | None = self._state()
        if st is None:
            return ""
        return _build_prompt(
            phase=st.phase,
            iteration=st.iteration,
            max_iterations=st.max_iterations,
            agent_count=st.agent_count,
            agent_role=st.agent_role,
            loop_dir=st.loop_dir,
            fix_attempts=st.fix_attempts,
            max_fix_attempts=st.max_fix_attempts,
        )

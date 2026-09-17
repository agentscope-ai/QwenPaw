# -*- coding: utf-8 -*-
"""Autopilot gate — lifecycle pipeline with cleanup + completed."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.loop_gate import LoopGate

from ..shared.constants import (
    AUTOPILOT_MAX_ITERATIONS,
    AUTOPILOT_MAX_PHASE_ITERATIONS,
    AUTOPILOT_MAX_VALIDATION_ROUNDS,
)
from ..shared.fork_guard import forks_integrated, merge_blocked_continuation
from ..shared.role_prompts import FORK_MERGE_PROTOCOL
from ..shared.state import WorkflowState
from .prompts import build_continuation as _build_prompt

_POST_FORK_PHASES = frozenset(
    {"qa", "validation", "cleanup", "completed"},
)


@dataclass
class _AutopilotState:
    loop_dir: Path
    workspace_dir: Path
    active: bool = True
    iteration: int = 0
    max_iterations: int = AUTOPILOT_MAX_ITERATIONS
    phase_entry_iteration: dict[str, int] = field(
        default_factory=dict,
    )
    skip_qa: bool = False
    skip_validation: bool = False
    validation_round: int = 0
    max_validation_rounds: int = AUTOPILOT_MAX_VALIDATION_ROUNDS
    phase: str = "expansion"
    blocked_on_merge: bool = False


class AutopilotGate(LoopGate):
    """Stop gate for the 6-phase Autopilot pipeline."""

    @property
    def name(self) -> str:
        return "autopilot"

    @property
    def priority(self) -> int:
        return 50

    def activate_for_autopilot(
        self,
        workspace_dir: Path,
        skip_qa: bool = False,
        skip_validation: bool = False,
    ) -> Path:
        try:
            from qwenpaw.agents.fork_project import begin_fork_scope

            begin_fork_scope(workspace_dir)
        except ImportError:
            import logging

            logging.getLogger(__name__).warning(
                "begin_fork_scope unavailable; fork merge scope disabled",
            )
        wf = WorkflowState(workspace_dir, "autopilot")
        loop_dir = wf.create_instance()
        state = _AutopilotState(
            loop_dir=loop_dir,
            workspace_dir=workspace_dir,
            skip_qa=skip_qa,
            skip_validation=skip_validation,
        )
        wf.write_state(
            {
                "phase": "expansion",
                "validation_round": 0,
            },
        )
        self.activate(state)
        return loop_dir

    async def check(  # pylint: disable=too-many-return-statements
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        if isinstance(ctx, dict) and ctx.get("has_tool_calls"):
            return StopHandlerResult(action=StopAction.BYPASS)

        st: _AutopilotState | None = self._state()
        if st is None:
            return StopHandlerResult(
                action=StopAction.BYPASS,
            )

        wf = WorkflowState.from_existing(
            st.workspace_dir,
            "autopilot",
            st.loop_dir,
        )
        data = await asyncio.to_thread(wf.read_state)

        phase = data.get("phase", "expansion")
        st.phase = phase
        st.validation_round = data.get(
            "validation_round",
            st.validation_round,
        )

        if phase in _POST_FORK_PHASES:
            integrated = await asyncio.to_thread(
                forks_integrated,
                data,
                st.workspace_dir,
            )
            if not integrated:
                # Preserve target phase; do not burn iteration/stall budget
                # while waiting on merge (same as Ultrawork).
                st.blocked_on_merge = True
                st.phase = phase
                await asyncio.to_thread(
                    wf.update_state,
                    {
                        "merge_blocked": True,
                        "resume_phase": phase,
                    },
                )
                return StopHandlerResult(
                    action=StopAction.INTERRUPT_AND_CONTINUE,
                    reason="Autopilot blocked: forks not integrated",
                )

        if data.get("merge_blocked"):
            await asyncio.to_thread(
                wf.update_state,
                {"merge_blocked": False},
            )
        st.blocked_on_merge = False

        st.iteration += 1
        if st.iteration > st.max_iterations:
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"Total iteration limit ({st.max_iterations})",
            )

        if phase == "completed":
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="Autopilot completed",
            )

        if (
            phase == "validation"
            and st.validation_round > st.max_validation_rounds
        ):
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=(
                    f"Validation round limit " f"({st.max_validation_rounds})"
                ),
            )

        if phase not in st.phase_entry_iteration:
            st.phase_entry_iteration[phase] = st.iteration
        elif (
            st.iteration - st.phase_entry_iteration[phase]
            > AUTOPILOT_MAX_PHASE_ITERATIONS
        ):
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"Phase '{phase}' stalled",
            )

        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="Autopilot in progress",
        )

    def build_continuation(self) -> str:
        """Build Autopilot continuation from gate state."""
        st: _AutopilotState | None = self._state()
        if st is None:
            return ""
        if st.blocked_on_merge:
            return merge_blocked_continuation(FORK_MERGE_PROTOCOL)
        return _build_prompt(
            phase=st.phase,
            iteration=st.iteration,
            max_iterations=st.max_iterations,
            loop_dir=st.loop_dir,
            skip_qa=st.skip_qa,
            skip_validation=st.skip_validation,
            validation_round=st.validation_round,
            max_validation_rounds=st.max_validation_rounds,
        )

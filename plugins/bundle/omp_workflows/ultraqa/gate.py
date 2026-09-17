# -*- coding: utf-8 -*-
"""UltraQA gate — 3-agent QA cycle with stop conditions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.loop_gate import LoopGate

from ..shared.constants import ULTRAQA_MAX_CYCLES, ULTRAQA_MAX_SAME_FAILURE
from ..shared.state import WorkflowState
from .prompts import build_continuation as _build_prompt


@dataclass
class _UltraQAState:
    loop_dir: Path
    workspace_dir: Path
    active: bool = True
    cycle: int = 0
    max_cycles: int = ULTRAQA_MAX_CYCLES
    goal_type: str = "tests"
    custom_cmd: str = ""
    interactive: bool = False
    qa_passed: bool = False
    last_failures: list[str] = field(default_factory=list)


class UltraQAGate(LoopGate):
    """Stop gate for the UltraQA 3-agent cycle."""

    @property
    def name(self) -> str:
        return "ultraqa"

    @property
    def priority(self) -> int:
        return 50

    def activate_for_qa(
        self,
        workspace_dir: Path,
        goal_type: str = "tests",
        custom_cmd: str = "",
        interactive: bool = False,
        max_cycles: int = ULTRAQA_MAX_CYCLES,
    ) -> Path:
        """Create state directory and activate the gate."""
        wf = WorkflowState(workspace_dir, "ultraqa")
        loop_dir = wf.create_instance()
        state = _UltraQAState(
            loop_dir=loop_dir,
            workspace_dir=workspace_dir,
            max_cycles=max_cycles,
            goal_type=goal_type,
            custom_cmd=custom_cmd,
            interactive=interactive,
        )
        wf.write_state(
            {
                "cycle": 0,
                "qa_passed": False,
                "last_failures": [],
            },
        )
        self.activate(state)
        return loop_dir

    async def check(self, ctx: Any) -> Optional[StopHandlerResult]:
        if isinstance(ctx, dict) and ctx.get("has_tool_calls"):
            return StopHandlerResult(action=StopAction.BYPASS)

        st: _UltraQAState | None = self._state()
        if st is None:
            return StopHandlerResult(
                action=StopAction.BYPASS,
            )

        wf = WorkflowState.from_existing(
            st.workspace_dir,
            "ultraqa",
            st.loop_dir,
        )
        data = await asyncio.to_thread(wf.read_state)

        # Agent-owned fields — never overwritten by the gate.
        st.qa_passed = data.get("qa_passed", False)
        st.last_failures = data.get(
            "last_failures",
            st.last_failures,
        )

        if st.qa_passed:
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="QA goals achieved",
            )

        # Gate owns cycle in memory (single writer).
        if st.cycle >= st.max_cycles:
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"Reached max cycles ({st.max_cycles})",
            )

        if _repeated_failure(
            st.last_failures,
            ULTRAQA_MAX_SAME_FAILURE,
        ):
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="Same failure repeated too many times",
            )

        st.cycle += 1
        await asyncio.to_thread(
            wf.update_state,
            {"cycle": st.cycle},
        )

        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="QA cycle in progress",
        )

    def build_continuation(self) -> str:
        """Build QA cycle continuation from gate state."""
        st: _UltraQAState | None = self._state()
        if st is None:
            return ""
        return _build_prompt(
            cycle=st.cycle,
            max_cycles=st.max_cycles,
            goal_type=st.goal_type,
            custom_cmd=st.custom_cmd,
            last_failures=st.last_failures,
            loop_dir=st.loop_dir,
            interactive=st.interactive,
        )


def _repeated_failure(
    failures: list[str],
    threshold: int,
) -> bool:
    """Check if the most recent failure repeated >= threshold."""
    if len(failures) < threshold:
        return False
    last = failures[-1]
    return all(f == last for f in failures[-threshold:])

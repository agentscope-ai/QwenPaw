# -*- coding: utf-8 -*-
"""MissionGate — Gate-driven Mission Mode Phase 2.

Replaces the custom ``run_mission_phase2`` executor
with a StopHandler-compatible gate that checks
``prd.json`` completion after each agent turn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ...loop.gates.base import (
    StopAction,
    StopHandlerResult,
)
from ...loop.gates.loop_gate import LoopGate

logger = logging.getLogger(__name__)

_TERMINAL_PHASES = frozenset(
    {"completed", "max_iterations_reached"},
)
_EXEC_PHASES = frozenset(
    {"execution_confirmed", "execution"},
)


@dataclass
class _MissionState:
    """Per-session mission state."""

    loop_dir: Path
    active: bool = True
    phase: str = "prd_generation"


class MissionGate(LoopGate):
    """Check mission completion via prd.json.

    Activated when ``loop_config.json`` phase transitions
    to ``execution_confirmed`` or ``execution``.
    Each ``check()`` reads prd.json and returns:
    - STOP if all stories passed or phase is terminal
    - CONTINUE with remaining summary otherwise
    """

    @property
    def name(self) -> str:
        return "mission"

    @property
    def priority(self) -> int:
        return 50

    async def check(  # pylint: disable=too-many-return-statements
        self,
        ctx: Any,  # pylint: disable=unused-argument
    ) -> Optional[StopHandlerResult]:
        """Evaluate mission completion."""
        state: Optional[_MissionState] = self._state()
        if state is None:
            state = self._try_restore(ctx)
        if state is None or not state.active:
            return None

        from .state import (
            read_loop_config,
            read_prd,
        )

        cfg = read_loop_config(state.loop_dir)
        phase = cfg.get("current_phase", "")
        state.phase = phase

        if phase in _TERMINAL_PHASES:
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=f"Mission {phase}",
            )

        if phase not in _EXEC_PHASES:
            return None

        return self._eval_prd(
            read_prd(state.loop_dir),
            cfg,
        )

    def _eval_prd(
        self,
        prd: dict,
        cfg: dict,
    ) -> Optional[StopHandlerResult]:
        """Evaluate PRD completion status."""
        from .state import (
            get_all_passed,
        )

        if not prd:
            return None

        stories = prd.get("userStories", [])
        if not stories:
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="No user stories in prd.json",
            )

        if get_all_passed(prd):
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="All stories passed",
            )

        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=(self._remaining_summary(prd, cfg)),
            reason="Mission in progress",
        )

    def continuation_prompt(self) -> str:
        """Fallback prompt when check() returns None."""
        return ""

    def activate_for_mission(
        self,
        loop_dir: Path,
    ) -> None:
        """Activate with mission-specific state."""
        ms = _MissionState(
            loop_dir=loop_dir,
            phase="prd_generation",
        )
        self.activate(ms)

    def _try_restore(
        self,
        ctx: Any,
    ) -> Optional[_MissionState]:
        """Lazy-restore from session_state."""
        if isinstance(ctx, dict):
            ss = ctx.get("session_state")
        else:
            ss = getattr(ctx, "session_state", None)
        if not ss or not ss.get("mission_active"):
            return None
        loop_dir_str = ss.get("mission_loop_dir")
        if not loop_dir_str:
            return None
        ld = Path(loop_dir_str)
        if not ld.exists():
            return None
        ms = _MissionState(
            loop_dir=ld,
            phase=ss.get(
                "mission_phase",
                "execution",
            ),
        )
        self.activate(ms)
        logger.info(
            "MissionGate restored (loop_dir=%s)",
            ld,
        )
        return ms

    @staticmethod
    def _remaining_summary(
        prd: dict,
        cfg: dict,
    ) -> str:
        """Build remaining story summary."""
        stories = prd.get("userStories", [])
        remaining = [s for s in stories if not s.get("passes")]
        passed = len(stories) - len(remaining)
        max_iter = cfg.get("max_iterations", 20)
        lines = [
            f"[Mission] {passed}/{len(stories)} "
            f"stories passed. "
            f"{len(remaining)} remaining:",
        ]
        for s in remaining:
            sid = s.get("id", "?")
            title = s.get("title", "?")
            lines.append(f"  - {sid}: {title}")
        tail = (
            "\nContinue with the "
            "**worker - verifier** pipeline:\n"
            "1. Dispatch **workers** for remaining\n"
            "2. Dispatch **verifiers** for completed\n"
            "3. Update prd.json passes accordingly"
            f"\n\nMax iterations: {max_iter}"
        )
        lines.append(tail)
        return "\n".join(lines)


__all__ = ["MissionGate"]

# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""PRE_DISPATCH hook: block execution when doom loop paused."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..runtime.hooks import HookAction, HookBase, HookResult
from ..runtime.phases import Phase
from .doom_loop import DoomLoopAlert, DoomLoopState

if TYPE_CHECKING:
    from ..runtime.hooks import HookContext

logger = logging.getLogger(__name__)

_HITL_KEY = "_doom_loop_state"


def get_doom_loop_state(ctx: "HookContext") -> DoomLoopState:
    """Retrieve or create the per-session DoomLoopState."""
    state = ctx.mode_state.get(_HITL_KEY)
    if state is None:
        state = DoomLoopState()
        ctx.mode_state[_HITL_KEY] = state
    return state


class HitlPauseHook(HookBase):
    """Block the request when doom loop HITL is active.

    Checks ``DoomLoopState.paused`` in ``mode_state`` and
    returns SHORT_CIRCUIT with a user-visible message asking
    the user to decide.
    """

    phase = Phase.PRE_DISPATCH
    name = "hitl_pause_gate"
    priority = 5

    async def run(self, ctx: "HookContext") -> HookResult:
        """Short-circuit on first pause, resume on user reply."""
        state = get_doom_loop_state(ctx)
        if not state.paused:
            return HookResult()

        # Second call while paused = user replied;
        # unpause and let the request proceed.
        if getattr(state, "_alert_shown", False):
            state.paused = False
            state._alert_shown = False  # type: ignore[attr-defined]
            return HookResult()

        try:
            from agentscope.message import Msg, TextBlock

            alert = DoomLoopAlert(
                session_id=ctx.session_id,
                signal="escalate_hitl",
                message=(
                    "Repetitive behavior detected. "
                    "The loop is paused. "
                    "Reply to continue or use "
                    "/cancel."
                ),
                escalation_count=state.escalation_count,
            )
            ctx.extras["_doom_loop_alert"] = alert.to_dict()

            payload = Msg(
                name="system",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(f"[Loop paused] " f"{alert.message}"),
                    ),
                ],
            )
            state._alert_shown = True  # type: ignore[attr-defined]
            return HookResult(
                action=HookAction.SHORT_CIRCUIT,
                payload=payload,
            )
        except Exception as exc:
            logger.warning(
                f"hitl_pause_gate error: {exc}",
            )
            return HookResult()


__all__ = [
    "HitlPauseHook",
    "get_doom_loop_state",
]

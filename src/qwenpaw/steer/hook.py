# -*- coding: utf-8 -*-
"""Hook that injects pending ``/steer`` guidance into the agent context."""

from __future__ import annotations

import logging
import time

from ..runtime.hooks import HookBase, HookContext, HookResult
from ..runtime.phases import Phase
from .store import pop_guidance

logger = logging.getLogger(__name__)


class SteerInjectionHook(HookBase):
    """Inject (and clear) pending steer guidance before the agent runs."""

    phase = Phase.PRE_AGENT_BUILD
    name = "steer_guidance_injection"
    # Run after the other context-setup hooks have done their work.
    priority = 90

    async def run(self, ctx: HookContext) -> HookResult:
        session_id = str(getattr(ctx, "session_id", "") or "")
        entry = pop_guidance(session_id)
        if entry is None:
            return HookResult()

        guidance, ts = entry
        issued = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        ctx.inject_context(
            content=(
                "## User Steering Guidance\n\n"
                f"> {guidance}\n\n"
                f"_(issued {issued})_\n\n"
                "Take this guidance into account for the current turn. "
                "Where it conflicts with an earlier instruction, this wins."
            ),
            priority=50,
            source="steer",
        )
        logger.info("[STEER] Injected guidance (session=%s)", session_id)
        return HookResult()


__all__ = ["SteerInjectionHook"]

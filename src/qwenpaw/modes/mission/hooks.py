# -*- coding: utf-8 -*-
"""Mission mode hooks — state load/save around the agent lifecycle."""

from __future__ import annotations

import logging

from ..base import ModeGatedHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class MissionStateLoadHook(ModeGatedHook):
    """Load mission state from session into ``ctx.mode_state["mission"]``."""

    phase = Phase.PRE_AGENT_BUILD
    name = "mission_state_load"
    priority = 30
    after = ("session_load",)

    async def _run(self, ctx: HookContext) -> HookResult:
        state = ctx.session_state or {}
        payload = state.get("mission_payload")
        if not payload:
            return HookResult()
        try:
            # pylint: disable-next=no-name-in-module
            from ...agents.mission.state import MissionState

            ctx.mode_state.setdefault("mission", {})[
                "state"
            ] = MissionState.from_dict(payload)
        except Exception:
            logger.debug("mission_state_load: failed", exc_info=True)
        return HookResult()


class MissionStateSaveHook(ModeGatedHook):
    """Persist mission state back to session after response."""

    phase = Phase.POST_RESPONSE
    name = "mission_state_save"
    priority = 30

    async def _run(self, ctx: HookContext) -> HookResult:
        ms = (ctx.mode_state.get("mission") or {}).get("state")
        if ms is None:
            return HookResult()
        try:
            if ctx.session_state is not None:
                ctx.session_state["mission_payload"] = ms.to_dict()
        except Exception:
            logger.debug("mission_state_save: failed", exc_info=True)
        return HookResult()


__all__ = ["MissionStateLoadHook", "MissionStateSaveHook"]

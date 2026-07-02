# -*- coding: utf-8 -*-
"""Mission mode hooks — state load/save around the agent lifecycle.

NOTE: ``MissionState`` class was removed (dead code).
These hooks are retained as no-ops for the MissionMode
hook registry.  Implement real logic when session-level
mission persistence is needed.
"""

from __future__ import annotations

import logging

from ..base import ModeGatedHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class MissionStateLoadHook(ModeGatedHook):
    """Load mission state (no-op placeholder)."""

    phase = Phase.PRE_AGENT_BUILD
    name = "mission_state_load"
    priority = 30
    after = ("session_load",)

    async def _run(
        self,
        ctx: HookContext,  # pylint: disable=unused-argument
    ) -> HookResult:
        return HookResult()


class MissionStateSaveHook(ModeGatedHook):
    """Persist mission state (no-op placeholder)."""

    phase = Phase.POST_RESPONSE
    name = "mission_state_save"
    priority = 30

    async def _run(
        self,
        ctx: HookContext,  # pylint: disable=unused-argument
    ) -> HookResult:
        return HookResult()


__all__ = [
    "MissionStateLoadHook",
    "MissionStateSaveHook",
]

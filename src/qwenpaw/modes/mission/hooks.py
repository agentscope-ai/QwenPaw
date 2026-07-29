# -*- coding: utf-8 -*-
"""Mission mode hooks for the existing session lifecycle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..base import ModeGatedHook
from ...runtime.hooks import HookBase, HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from . import MissionMode


class MissionStateLoadHook(ModeGatedHook):
    """Preserve Mission hook ordering after generic session state load."""

    phase = Phase.PRE_AGENT_BUILD
    name = "mission_state_load"
    priority = 30
    after = ("session_load",)

    async def _run(
        self,
        ctx: HookContext,  # pylint: disable=unused-argument
    ) -> HookResult:
        return HookResult()


class MissionStateSaveHook(HookBase):
    """Refresh mission mode_state before the session save hook runs."""

    phase = Phase.POST_RESPONSE
    name = "mission_state_save"
    priority = 30
    before = ("session_save",)

    def __init__(self, owner_mode: "MissionMode") -> None:
        self.owner_mode = owner_mode

    async def run(
        self,
        ctx: HookContext,
    ) -> HookResult:
        await self.owner_mode.sync_persistent_state(ctx)
        return HookResult()


class MissionStateSaveOnCancelHook(HookBase):
    """Refresh mission mode state before cancel-path session persistence."""

    phase = Phase.ON_CANCEL
    name = "mission_state_save_on_cancel"
    priority = 30
    after = ("cancel_response_injection",)
    before = ("session_save_on_cancel",)

    def __init__(self, owner_mode: "MissionMode") -> None:
        self.owner_mode = owner_mode

    async def run(
        self,
        ctx: HookContext,
    ) -> HookResult:
        await self.owner_mode.sync_persistent_state(ctx)
        return HookResult()


__all__ = [
    "MissionStateLoadHook",
    "MissionStateSaveHook",
    "MissionStateSaveOnCancelHook",
]

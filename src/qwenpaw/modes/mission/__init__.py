# -*- coding: utf-8 -*-
"""Mission mode — ``AgentMode`` for autonomous iterative tasks.

Exposes hooks and a prompt contributor so the Runtime lifecycle drives
mission state load/save.  Domain logic (state machine, PRD generation,
iteration loop) lives in ``agents.mission``.
"""

from __future__ import annotations

from ..base import AgentMode
from ...runtime.hooks import HookBase, HookContext


class MissionMode(AgentMode):
    """Bundle for mission-mode behaviour."""

    name = "mission"

    def hooks(self) -> list[HookBase]:
        from .hooks import MissionStateLoadHook, MissionStateSaveHook

        return [
            MissionStateLoadHook(owner_mode=self),
            MissionStateSaveHook(owner_mode=self),
        ]

    def prompt_contributors(self) -> list:
        from .contributor import MissionPromptContributor

        return [MissionPromptContributor(owner_mode=self)]

    def is_active(self, ctx: HookContext) -> bool:
        return bool((ctx.session_state or {}).get("mission_active"))


__all__ = ["MissionMode"]

# -*- coding: utf-8 -*-
"""Mission mode prompt contributor.

Delegates to ``agents/mission/prompts.py``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...runtime.prompt_manager import SyncPromptContributor

if TYPE_CHECKING:
    from ..base import AgentMode

logger = logging.getLogger(__name__)


class MissionPromptContributor(SyncPromptContributor):
    """Inject mission guidance into the system prompt.

    Used when mission is active.
    """

    name = "mission_prompt"
    priority = 25

    def __init__(self, owner_mode: "AgentMode") -> None:
        self.owner_mode = owner_mode

    def contribute_sync(self, ctx: object) -> str | None:
        from ...runtime.hooks import HookContext

        if not isinstance(ctx, HookContext):
            return None
        if not self.owner_mode.is_active(ctx):
            return None
        ms = (ctx.mode_state.get("mission") or {}).get("state")
        if ms is None:
            return None
        try:
            # pylint: disable-next=no-name-in-module
            from ...agents.mission.prompts import (
                build_mission_system_prompt,
            )

            return build_mission_system_prompt(ms)
        except Exception:
            logger.debug("mission_prompt: contribute failed", exc_info=True)
            return None


__all__ = ["MissionPromptContributor"]

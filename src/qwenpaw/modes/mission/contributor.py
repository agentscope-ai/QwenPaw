# -*- coding: utf-8 -*-
"""Mission mode prompt contributor.

NOTE: ``build_mission_system_prompt`` was removed
(dead code — never existed in prompts.py).  This
contributor is retained as a no-op placeholder for
the MissionMode prompt contributor registry.
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

    Currently a no-op; real implementation pending.
    """

    name = "mission_prompt"
    priority = 25

    def __init__(self, owner_mode: "AgentMode") -> None:
        self.owner_mode = owner_mode

    def contribute_sync(
        self,
        ctx: object,  # pylint: disable=unused-argument
    ) -> str | None:
        return None


__all__ = ["MissionPromptContributor"]

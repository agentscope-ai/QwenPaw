# -*- coding: utf-8 -*-
"""Goal-mode prompt contributor."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...runtime.prompt_manager import (
    SyncPromptContributor,
)

if TYPE_CHECKING:
    from ...runtime.hooks import HookContext


class GoalPromptContributor(SyncPromptContributor):
    """Inject goal context into the system prompt."""

    name = "goal-mode-skill"
    priority = 120

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def contribute_sync(
        self,
        ctx: "HookContext",  # noqa: ARG002
    ) -> str | None:
        """Return goal prompt when a session is active."""
        return self._owner.prompt_provider(None)


__all__ = ["GoalPromptContributor"]

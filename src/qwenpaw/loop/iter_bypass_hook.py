# -*- coding: utf-8 -*-
"""POST_AGENT_BUILD hook: lift ReAct max_iters when a loop is active.

When any loop (GoalMode or plugin loop) is active, the ReAct
iteration limit should not interfere — the loop's own budget
(iteration count + token budget + doom loop detector) controls
when the agent stops.

This hook bumps ``react_config.max_iters`` to a very large value
after the agent is built, and a paired POST_RESPONSE hook
restores the original value.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from ..runtime.hooks import HookBase, HookResult
from ..runtime.phases import Phase

if TYPE_CHECKING:
    from ..runtime.hooks import HookContext

logger = logging.getLogger(__name__)

_BYPASS_ITERS = 999_999
_SAVED_KEY = "_loop_saved_max_iters"


class LoopIterBypassHook(HookBase):
    """Bump ReAct max_iters when a loop is active."""

    phase = Phase.POST_AGENT_BUILD
    name = "loop_iter_bypass"
    priority = 10

    def __init__(
        self,
        is_active_fn: Callable[[], bool],
    ) -> None:
        self._is_active = is_active_fn

    async def run(
        self,
        ctx: "HookContext",
    ) -> HookResult:
        """Lift max_iters if any loop is active."""
        if not self._is_active():
            return HookResult()

        agent = ctx.agent
        if agent is None:
            return HookResult()

        rc = getattr(agent, "react_config", None)
        if rc is None:
            return HookResult()

        original = getattr(rc, "max_iters", None)
        if original is None or original >= _BYPASS_ITERS:
            return HookResult()

        ctx.extras[_SAVED_KEY] = original
        try:
            from agentscope.agent import ReActConfig

            agent.react_config = ReActConfig(
                max_iters=_BYPASS_ITERS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Failed to bypass max_iters: {exc}",
            )

        logger.info(
            "Loop active: max_iters %d -> %d",
            original,
            _BYPASS_ITERS,
        )
        return HookResult()


class LoopIterRestoreHook(HookBase):
    """Restore original max_iters after execution."""

    phase = Phase.POST_RESPONSE
    name = "loop_iter_restore"
    priority = 90

    async def run(
        self,
        ctx: "HookContext",
    ) -> HookResult:
        """Restore saved max_iters."""
        saved = ctx.extras.pop(_SAVED_KEY, None)
        if saved is None:
            return HookResult()

        agent = ctx.agent
        if agent is None:
            return HookResult()

        try:
            from agentscope.agent import ReActConfig

            agent.react_config = ReActConfig(
                max_iters=saved,
            )
            logger.info(
                "Loop done: max_iters restored to %d",
                saved,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Failed to restore max_iters: {exc}",
            )
        return HookResult()


__all__ = [
    "LoopIterBypassHook",
    "LoopIterRestoreHook",
]

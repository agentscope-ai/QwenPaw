# -*- coding: utf-8 -*-
"""Retiring a Computer Use turn when the request that opened it finishes.

The host mints a fresh turn id for every request, in a request-setup hook. This
is the other half of that: a hook in the FINALLY phase, which the runtime runs
inside a `finally` block, so the turn is released whether the request
succeeded,
failed or was cancelled.

Without it nothing ever told the plugin a turn was over. A session that used
the
tool once went on claiming its turn -- holding the connection, and holding the
helper's screenshots and accessibility handles for that turn -- until some
later
request happened to arrive with a different id.
"""

from __future__ import annotations

import logging

from qwenpaw.hooks.base import LifecycleHook
from qwenpaw.runtime.hooks import HookContext, HookResult
from qwenpaw.runtime.phases import Phase

from .client import end_computer_use_turn

logger = logging.getLogger(__name__)


class ComputerUseTurnEndHook(LifecycleHook):
    """Release the native turn a finished request was holding."""

    phase = Phase.FINALLY
    name = "computer_use_turn_end"
    priority = 50

    async def run(self, ctx: HookContext) -> HookResult:
        session_id = getattr(ctx, "session_id", "") or ""
        if not session_id:
            return HookResult()
        try:
            await end_computer_use_turn(session_id)
        except Exception:  # noqa: BLE001 - cleanup must not fail a request
            logger.debug(
                "computer_use_turn_end: release failed session=%s",
                session_id,
                exc_info=True,
            )
        return HookResult()


__all__ = ["ComputerUseTurnEndHook"]

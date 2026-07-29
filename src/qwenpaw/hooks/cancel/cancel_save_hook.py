# -*- coding: utf-8 -*-
"""Cancel-path response repair and incomplete-state persistence."""

from __future__ import annotations

from ..base import LifecycleHook
from ...runtime._cancel_utils import repair_interrupted_response
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase


class CancelResponseInjectionHook(LifecycleHook):
    """Repair interrupted response state before persistence hooks run."""

    phase = Phase.ON_CANCEL
    name = "cancel_response_injection"
    priority = 10

    async def run(self, ctx: HookContext) -> HookResult:
        if ctx.agent is not None and ctx.envelope is not None:
            repair_interrupted_response(ctx.agent, ctx.envelope)
        return HookResult()


__all__ = ["CancelResponseInjectionHook"]

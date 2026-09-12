# -*- coding: utf-8 -*-
"""Prepare the effective model once for each runtime request."""

from __future__ import annotations

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase
from ...services.model_selection import prepare_model_context


class ModelContextHook(LifecycleHook):
    """Persist a request override and expose one resolved model context."""

    phase = Phase.PRE_DISPATCH
    name = "model_context"
    priority = 20

    async def run(self, ctx: HookContext) -> HookResult:
        request = ctx.request
        await prepare_model_context(
            workspace=ctx.workspace,
            session_id=ctx.session_id,
            user_id=getattr(request, "user_id", "") or ctx.session_id,
            channel=getattr(request, "channel", "") or "console",
            request_override=getattr(request, "model_slot_override", None),
        )
        return HookResult()


__all__ = ["ModelContextHook"]

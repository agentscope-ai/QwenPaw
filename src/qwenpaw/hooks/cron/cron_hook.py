# -*- coding: utf-8 -*-
"""Cron context hook.

Marks cron-originated requests so downstream hooks can adjust behavior
(e.g. BootstrapHook skips guidance injection for cron requests).
"""

from __future__ import annotations

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

IS_CRON_KEY = "is_cron"


class CronContextHook(LifecycleHook):
    """Tag cron-originated requests early in the pipeline."""

    phase = Phase.PRE_DISPATCH
    name = "cron_context"
    priority = 5

    async def run(self, ctx: HookContext) -> HookResult:
        source = getattr(ctx.request, "session_source", None)
        if source == "cron":
            ctx.extras[IS_CRON_KEY] = True
        return HookResult()


__all__ = ["CronContextHook", "IS_CRON_KEY"]

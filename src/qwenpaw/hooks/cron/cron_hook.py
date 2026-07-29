# -*- coding: utf-8 -*-
"""Cron lifecycle hooks.

- CronContextHook: marks cron-originated requests so downstream hooks
  can adjust behavior (e.g. BootstrapHook skips guidance injection).
- CronMemoryIsolateHook / CronMemoryRestoreHook: snapshot & clear
  agent memory before execution, then restore the full history plus
  new messages afterward so each cron run is context-free while the
  persisted session still accumulates all runs' conversations.
"""

from __future__ import annotations

import logging

from ..base import LifecycleHook
from ...runtime._incomplete_state import (
    CRON_CONTEXT_SNAPSHOT_KEY,
    CRON_SUMMARY_SNAPSHOT_KEY,
    restore_cron_memory,
)
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)

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


class CronMemoryIsolateHook(LifecycleHook):
    """Snapshot and clear agent context so cron runs execute without
    prior conversation history.

    In 2.0, conversation context lives in ``agent.state.context``
    (an ``AgentState`` pydantic model), not ``agent.memory``.

    Runs at PRE_EXECUTE (after agent build + session load) so the
    agent's state already contains the full history at this point.
    """

    phase = Phase.PRE_EXECUTE
    name = "cron_memory_isolate"
    priority = 10

    async def run(self, ctx: HookContext) -> HookResult:
        if not ctx.extras.get(IS_CRON_KEY):
            return HookResult()
        agent = ctx.agent
        if agent is None:
            return HookResult()
        state = getattr(agent, "state", None)
        if state is None or not hasattr(state, "context"):
            return HookResult()
        ctx.extras[CRON_CONTEXT_SNAPSHOT_KEY] = list(state.context)
        ctx.extras[CRON_SUMMARY_SNAPSHOT_KEY] = getattr(
            state,
            "summary",
            "",
        )
        state.context.clear()
        if hasattr(state, "summary"):
            state.summary = ""
        logger.debug(
            "cron_memory_isolate: snapshotted %d msgs and cleared "
            "context for session_id=%s",
            len(ctx.extras[CRON_CONTEXT_SNAPSHOT_KEY]),
            ctx.session_id,
        )
        return HookResult()


class CronMemoryRestoreHook(LifecycleHook):
    """Restore snapshotted context and append new messages produced by
    the current cron run.

    Must run at POST_RESPONSE *before* SessionSaveHook (priority 90)
    so ``state_dict()`` captures the full history when persisted.
    """

    phase = Phase.POST_RESPONSE
    name = "cron_memory_restore"
    priority = 80

    async def run(self, ctx: HookContext) -> HookResult:
        restore_cron_memory(ctx)
        return HookResult()


class CronMemoryRestoreOnCancelHook(LifecycleHook):
    """Restore isolated cron history before cancel-path persistence."""

    phase = Phase.ON_CANCEL
    name = "cron_memory_restore_on_cancel"
    priority = 80
    after = ("cancel_response_injection",)

    async def run(self, ctx: HookContext) -> HookResult:
        restore_cron_memory(ctx)
        return HookResult()


__all__ = [
    "CronContextHook",
    "CronMemoryIsolateHook",
    "CronMemoryRestoreHook",
    "CronMemoryRestoreOnCancelHook",
    "IS_CRON_KEY",
    "restore_cron_memory",
]

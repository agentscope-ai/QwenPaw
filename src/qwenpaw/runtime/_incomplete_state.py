# -*- coding: utf-8 -*-
"""Shared persistence primitives for interrupted and failed requests.

This module sits below concrete lifecycle hooks so both ``Runtime`` and
hook wrappers can reuse the same state operations without a
``runtime -> hooks -> runtime`` dependency cycle.
"""

from __future__ import annotations

import asyncio
import copy
import logging

from ..agents.acp.meta import ACP_EPHEMERAL_META_KEY
from ._cancel_utils import repair_interrupted_response
from ._state_utils import StateProxy
from .hooks import HookContext

logger = logging.getLogger(__name__)

CRON_CONTEXT_SNAPSHOT_KEY = "_cron_context_snapshot"
CRON_SUMMARY_SNAPSHOT_KEY = "_cron_summary_snapshot"


def is_ephemeral_request(ctx: HookContext) -> bool:
    """Return whether the request must not touch persistent session state."""
    request_context = getattr(ctx.request, "request_context", None)
    if not isinstance(request_context, dict):
        return False
    value = request_context.get(ACP_EPHEMERAL_META_KEY)
    if value is True:
        return True
    return isinstance(value, str) and value.lower() in {"1", "true", "yes"}


def build_session_snapshot(ctx: HookContext) -> StateProxy | None:
    """Synchronously snapshot independent agent and mode state."""
    if is_ephemeral_request(ctx):
        return None
    if ctx.workspace is None or ctx.agent is None:
        return None
    if getattr(ctx.workspace, "session", None) is None:
        return None

    proxy = StateProxy()
    proxy.data = ctx.agent.state_dict()
    proxy.data["mode_state"] = copy.deepcopy(ctx.mode_state)
    return proxy


async def save_session_snapshot(
    ctx: HookContext,
    proxy: StateProxy,
) -> None:
    """Persist an already-independent session snapshot."""
    session = getattr(ctx.workspace, "session", None)
    if session is None:
        return
    user_id = getattr(ctx.request, "user_id", "") or ctx.session_id
    channel = getattr(ctx.request, "channel", "") or ""
    await session.save_session_state(
        session_id=ctx.session_id,
        user_id=user_id,
        channel=channel,
        agent=proxy,
    )


def restore_cron_memory(ctx: HookContext) -> bool:
    """Transactionally restore a cron snapshot exactly once.

    If context or summary replacement fails, the isolated state is restored
    and the snapshot remains available for a later retry.
    """
    snapshot = ctx.extras.get(CRON_CONTEXT_SNAPSHOT_KEY)
    if snapshot is None:
        return False
    agent = ctx.agent
    if agent is None:
        return False
    state = getattr(agent, "state", None)
    if state is None or not hasattr(state, "context"):
        return False

    new_messages: list = []
    current_summary = ""
    mutation_started = False
    try:
        new_messages = list(state.context)
        current_summary = getattr(state, "summary", "")
        old_summary = ctx.extras.get(CRON_SUMMARY_SNAPSHOT_KEY, "")
        restored_context = [*snapshot, *new_messages]
        mutation_started = True
        state.context[:] = restored_context
        if hasattr(state, "summary"):
            state.summary = old_summary
    except Exception:
        if mutation_started:
            try:
                state.context[:] = new_messages
                if hasattr(state, "summary"):
                    state.summary = current_summary
            except Exception:
                logger.error(
                    "cron_memory_restore: rollback failed for session_id=%s",
                    ctx.session_id,
                    exc_info=True,
                )
        logger.warning(
            "cron_memory_restore: failed for session_id=%s",
            ctx.session_id,
            exc_info=True,
        )
        return False

    ctx.extras.pop(CRON_CONTEXT_SNAPSHOT_KEY, None)
    ctx.extras.pop(CRON_SUMMARY_SNAPSHOT_KEY, None)
    logger.debug(
        "cron_memory_restore: restored %d historical + %d new "
        "messages for session_id=%s",
        len(snapshot),
        len(new_messages),
        ctx.session_id,
    )
    return True


async def persist_incomplete_state(ctx: HookContext) -> None:
    """Best-effort state save for a non-cancellation runtime failure."""
    try:
        if ctx.agent is not None and ctx.envelope is not None:
            repair_interrupted_response(ctx.agent, ctx.envelope)
        restore_cron_memory(ctx)
        proxy = build_session_snapshot(ctx)
        if proxy is None:
            return

        task = asyncio.create_task(
            save_session_snapshot(ctx, proxy),
            name=f"incomplete-save:{ctx.session_id}",
        )
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
    except asyncio.CancelledError:
        logger.debug(
            "incomplete-state save task was cancelled (session=%s)",
            ctx.session_id,
        )
    except Exception:
        logger.debug(
            "incomplete-state save failed (session=%s)",
            ctx.session_id,
            exc_info=True,
        )


__all__ = [
    "CRON_CONTEXT_SNAPSHOT_KEY",
    "CRON_SUMMARY_SNAPSHOT_KEY",
    "build_session_snapshot",
    "is_ephemeral_request",
    "persist_incomplete_state",
    "restore_cron_memory",
    "save_session_snapshot",
]

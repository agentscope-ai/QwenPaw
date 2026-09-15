# -*- coding: utf-8 -*-
"""Session load/save lifecycle hooks.

Loads persisted session state into ``ctx.session_state`` (PRE_AGENT_BUILD)
so the builder can inject it into the newly-constructed agent. Saves
agent state back to session storage after the response completes.
"""

from __future__ import annotations

import asyncio
import logging

from ..cron.cron_hook import restore_cron_context
from ...agents.acp.meta import ACP_EPHEMERAL_META_KEY
from ...runtime._state_utils import StateProxy
from ...runtime.console_turn_state import (
    prepare_console_regeneration,
    repair_invalid_history_images,
    stamp_console_turn,
)
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase
from ..base import LifecycleHook
from .signals import SESSION_SAVE_SUCCEEDED_KEY, record_session_save

logger = logging.getLogger(__name__)


def _is_ephemeral_request(ctx: HookContext) -> bool:
    request = ctx.request
    request_context = getattr(request, "request_context", None)
    if isinstance(request_context, dict):
        value = request_context.get(ACP_EPHEMERAL_META_KEY)
        if value is True:
            return True
        if isinstance(value, str) and value.lower() in {"1", "true", "yes"}:
            return True
    return False


class SessionLoadHook(LifecycleHook):
    """Load persisted session state before agent construction."""

    phase = Phase.PRE_AGENT_BUILD
    name = "session_load"
    priority = 10

    async def run(self, ctx: HookContext) -> HookResult:
        if _is_ephemeral_request(ctx):
            return HookResult()
        if ctx.workspace is None:
            return HookResult()
        session = getattr(ctx.workspace, "session", None)
        if session is None:
            return HookResult()
        try:
            request = ctx.request
            user_id = getattr(request, "user_id", "") or ctx.session_id
            channel = getattr(request, "channel", "") or ""

            proxy = StateProxy()
            await session.load_session_state(
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
                agent=proxy,
            )
            if proxy.data:
                ctx.session_state = proxy.data
                mode_state = proxy.data.get("mode_state")
                if isinstance(mode_state, dict):
                    loaded_mode_state = dict(mode_state)
                    loaded_mode_state.update(ctx.mode_state)
                    ctx.mode_state = loaded_mode_state
        except KeyError as e:
            logger.debug(
                "session_load: skipped (schema mismatch): %s",
                e,
            )
        except Exception:
            logger.debug("session_load: failed", exc_info=True)
        if ctx.session_state:
            prepare_console_regeneration(ctx.session_state, ctx.request)
            if getattr(ctx.request, "channel", None) == "console":
                await asyncio.to_thread(
                    repair_invalid_history_images,
                    ctx.session_state,
                )
        return HookResult()


class SessionSaveHook(LifecycleHook):
    """Persist agent state after response completion."""

    phase = Phase.POST_RESPONSE
    name = "session_save"
    priority = 90

    async def run(self, ctx: HookContext) -> HookResult:
        ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] = False
        if _is_ephemeral_request(ctx):
            return HookResult()
        if ctx.workspace is None or ctx.agent is None:
            return HookResult()
        session = getattr(ctx.workspace, "session", None)
        if session is None:
            return HookResult()
        try:
            restore_cron_context(ctx)
            proxy = StateProxy()
            proxy.data = ctx.agent.state_dict()
            stamp_console_turn(proxy.data, ctx.request, "completed")
            proxy.data["mode_state"] = ctx.mode_state
            await save_snapshot(ctx, proxy)
        except Exception:
            logger.debug("session_save: failed", exc_info=True)
        return HookResult()


async def save_snapshot(ctx: HookContext, proxy: StateProxy) -> None:
    """Join storage I/O before propagating repeated cancellation."""
    record_session_save(ctx, False)
    request = ctx.request
    write = asyncio.create_task(
        ctx.workspace.session.save_session_state(
            session_id=ctx.session_id,
            user_id=getattr(request, "user_id", "") or ctx.session_id,
            channel=getattr(request, "channel", "") or "",
            agent=proxy,
        )
    )
    cancelled = False
    try:
        while not write.done():
            try:
                await asyncio.shield(write)
            except asyncio.CancelledError:
                cancelled = True
        write.result()
    except Exception as error:
        if cancelled:
            raise asyncio.CancelledError from error
        raise
    record_session_save(ctx, True)
    if cancelled:
        raise asyncio.CancelledError


__all__ = ["SessionLoadHook", "SessionSaveHook", "save_snapshot"]

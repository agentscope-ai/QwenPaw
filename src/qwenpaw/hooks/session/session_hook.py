# -*- coding: utf-8 -*-
"""Session load/save lifecycle hooks.

Loads persisted session state into ``ctx.session_state`` (PRE_AGENT_BUILD)
so the builder can inject it into the newly-constructed agent. Saves
agent state back to session storage after the response completes.
"""

from __future__ import annotations

import asyncio
import logging

from ..._session_request import is_ephemeral_request
from ..base import LifecycleHook
from ..cron.cron_hook import restore_cron_context
from ...runtime._state_utils import StateProxy
from ...runtime.console_turn_state import (
    prepare_console_regeneration,
    repair_invalid_history_images,
    stamp_console_turn,
)
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase
from ..._session_signals import (
    SESSION_SAVE_SUCCEEDED_KEY,
    TRANSCRIPT_RECORDING_READY_KEY,
    TRANSCRIPT_TURN_ID_CONTEXT_KEY,
    TURN_COMMIT_KEY,
)

logger = logging.getLogger(__name__)


def _is_ephemeral_request(ctx: HookContext) -> bool:
    return is_ephemeral_request(ctx.request)


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
        except Exception:
            logger.exception("session_load: failed")
            raise
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
            request = ctx.request
            user_id = getattr(request, "user_id", "") or ctx.session_id
            channel = getattr(request, "channel", "") or ""

            restore_cron_context(ctx)
            proxy = StateProxy()
            proxy.data = ctx.agent.state_dict()
            stamp_console_turn(proxy.data, request, "completed")
            proxy.data["mode_state"] = ctx.mode_state
            save = session.save_session_state
            save_kwargs = {}
            request_context = getattr(request, "request_context", None) or {}
            turn_id = request_context.get(TRANSCRIPT_TURN_ID_CONTEXT_KEY)
            if (
                turn_id
                and request_context.get(TRANSCRIPT_RECORDING_READY_KEY)
                and callable(
                    getattr(type(session), "save_turn_session_state", None),
                )
            ):
                save = session.save_turn_session_state
                save_kwargs["turn_id"] = str(turn_id)
                if TURN_COMMIT_KEY in request_context:
                    save_kwargs["pending_commit"] = request_context[
                        TURN_COMMIT_KEY
                    ]
            await save(
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
                agent=proxy,
                **save_kwargs,
            )
            ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] = (
                "pending_commit" not in save_kwargs
            )
        except Exception:
            logger.exception("session_save: failed")
            raise
        return HookResult()


__all__ = ["SessionLoadHook", "SessionSaveHook"]

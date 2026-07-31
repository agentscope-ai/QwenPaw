# -*- coding: utf-8 -*-
"""Runtime hooks for built-in conversation checkpoints."""

from __future__ import annotations

import logging

from ..hooks.base import LifecycleHook
from ..hooks.session.signals import SESSION_SAVE_SUCCEEDED_KEY
from ..runtime.hooks import HookContext, HookResult
from ..runtime.phases import Phase

from .policy import context_channel
from .runtime import RUNTIME

logger = logging.getLogger("qwenpaw.checkpoints")


def _request_user_id(ctx: HookContext) -> str:
    request = getattr(ctx, "request", None)
    return getattr(request, "user_id", None) or ctx.session_id or ""


def _last_user_text(ctx: HookContext) -> str:
    if not ctx.input_msgs:
        return ""
    last = ctx.input_msgs[-1]
    if hasattr(last, "get_text_content"):
        return last.get_text_content() or ""
    return ""


def is_slash_like_input(text: str) -> bool:
    """Return whether *text* should be treated as slash-command input."""
    return (text or "").lstrip().startswith("/")


class CheckpointQueryGateHook(LifecycleHook):
    """Block new requests while checkpoint maintenance holds the gate."""

    phase = Phase.PRE_DISPATCH
    name = "checkpoint_query_gate"
    priority = 20

    async def run(self, ctx: HookContext) -> HookResult:
        try:
            if ctx.workspace is not None:
                engine = await RUNTIME.get_for_workspace_async(ctx.workspace)
                await engine.query_gate.wait()
        except Exception:
            logger.exception("Checkpoint query gate failed")
        return HookResult()


class CheckpointAutoSnapshotHook(LifecycleHook):
    """Schedule debounced auto checkpoints after session persistence."""

    phase = Phase.POST_RESPONSE
    name = "checkpoint_auto_snapshot"
    priority = 95
    after = ("session_save",)

    async def run(self, ctx: HookContext) -> HookResult:
        try:
            if ctx.workspace is None:
                return HookResult()
            if ctx.extras.get(SESSION_SAVE_SUCCEEDED_KEY) is not True:
                return HookResult()
            text = _last_user_text(ctx)
            if is_slash_like_input(text):
                return HookResult()
            await RUNTIME.schedule_auto_snapshot(
                ctx.workspace,
                session_id=ctx.session_id,
                user_id=_request_user_id(ctx),
                channel=context_channel(ctx),
                query_text=text or None,
            )
        except Exception:
            logger.exception("Checkpoint POST_RESPONSE auto snapshot failed")
        return HookResult()


__all__ = [
    "CheckpointAutoSnapshotHook",
    "CheckpointQueryGateHook",
    "is_slash_like_input",
]

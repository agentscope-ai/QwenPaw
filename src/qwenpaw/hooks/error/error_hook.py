# -*- coding: utf-8 -*-
"""Error handling hooks.

Exception normalization, error dump, and cancel cleanup as ON_ERROR hooks.
"""

from __future__ import annotations

import logging

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class ErrorNormalizeHook(LifecycleHook):
    """Normalize provider-specific exceptions into user-readable messages."""

    phase = Phase.ON_ERROR
    name = "error_normalize"
    priority = 10

    async def run(self, ctx: HookContext) -> HookResult:
        exc = ctx.error
        if exc is None:
            return HookResult()

        from ...exceptions import convert_model_exception

        model_name: str | None = None
        try:
            if ctx.agent is not None:
                _m = getattr(ctx.agent, "model", None)
                if _m is not None:
                    model_name = getattr(_m, "model_name", None) or getattr(
                        _m,
                        "name",
                        None,
                    )
        except Exception:
            pass

        if not isinstance(exc, Exception):
            return HookResult()

        normalized = convert_model_exception(exc, model_name=model_name)
        error_text = normalized.message or str(exc) or exc.__class__.__name__

        try:
            from ...app.chats.query_error_dump import write_query_error_dump

            dump_path = write_query_error_dump(
                ctx.request,
                exc,
                {"agent": ctx.agent},
            )
            if dump_path:
                error_text += f" [dump: {dump_path}]"
                logger.info("error_normalize: dump written to %s", dump_path)
        except Exception:
            logger.debug(
                "error_normalize: write_query_error_dump failed",
                exc_info=True,
            )

        ctx.extras["_error_text"] = error_text
        return HookResult()


class CancelCleanupHook(LifecycleHook):
    """Clean up pending approvals and interrupt agent on cancellation."""

    phase = Phase.ON_ERROR
    name = "cancel_cleanup"
    priority = 20

    async def run(self, ctx: HookContext) -> HookResult:
        import asyncio

        exc = ctx.error
        if not isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            return HookResult()

        logger.info(
            "cancel_cleanup: cancelled (session=%s): %s",
            ctx.session_id,
            type(exc).__name__,
        )

        try:
            from ...app.approvals import get_approval_service

            svc = get_approval_service()
            await svc.cancel_all_pending_by_root_session(
                ctx.root_session_id or ctx.session_id,
            )
        except Exception:
            logger.debug(
                "cancel_cleanup: approval cleanup failed",
                exc_info=True,
            )

        if ctx.agent is not None:
            interrupt_fn = getattr(ctx.agent, "interrupt", None)
            if interrupt_fn is not None:
                try:
                    interrupt_fn()
                except Exception:
                    pass

        return HookResult()


__all__ = ["ErrorNormalizeHook", "CancelCleanupHook"]

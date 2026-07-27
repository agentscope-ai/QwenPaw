# -*- coding: utf-8 -*-
"""Questionnaire cleanup hook.

Recycles pending questionnaire Futures when a run is cancelled or errors
out, so the frontend card doesn't hang waiting for an answer that will
never come.
"""

from __future__ import annotations

import logging

from ...hooks.base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class QuestionnaireCleanupHook(LifecycleHook):
    """Cancel any pending questionnaire for this session on cancel/error.

    Runs in FINALLY (guaranteed on all paths, unlike ON_ERROR which is
    skipped on asyncio re-cancellation). Only acts when ``ctx.error`` is
    set — on normal completion the questionnaire is already resolved and
    ``cancel_if_exists`` would be a no-op anyway.
    """

    phase = Phase.FINALLY
    name = "questionnaire_cleanup"
    priority = 30

    async def run(self, ctx: HookContext) -> HookResult:
        if ctx.error is None:
            return HookResult()

        from .service import get_question_service

        logger.info(
            "Questionnaire cleanup triggered in FINALLY: error=%s session=%s "
            "— attempting to cancel pending questionnaire",
            type(ctx.error).__name__,
            ctx.session_id,
        )
        try:
            await get_question_service().cancel_if_exists(ctx.session_id)
            logger.info(
                "Questionnaire cleanup cancelled pending questionnaire "
                "for session %s",
                ctx.session_id,
            )
        except Exception:
            logger.warning(
                "Questionnaire cleanup failed for session %s",
                ctx.session_id,
                exc_info=True,
            )
        return HookResult()


__all__ = ["QuestionnaireCleanupHook"]

# -*- coding: utf-8 -*-
"""Advisor mode hooks."""

from __future__ import annotations

import logging
from typing import Any

from ..base import ModeGatedHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase
from .config import resolve_agent_config
from .teacher import effective_teacher_slot, slot_to_dict

logger = logging.getLogger(__name__)


def _has_model_override(request: Any) -> bool:
    """Whether the request already names a model (explicit override)."""
    if getattr(request, "model_slot_override", None) is not None:
        return True
    payload_ctx = getattr(request, "request_context", None)
    return (
        isinstance(payload_ctx, dict)
        and payload_ctx.get("model_slot_override") is not None
    )


def _apply_model_override(request: Any, slot: dict[str, str]) -> bool:
    """Set ``model_slot_override`` on ``request``; ``True`` when it stuck."""
    try:
        setattr(request, "model_slot_override", dict(slot))
    except Exception:
        logger.warning(
            "Advisor Mode: could not set the student model override",
            exc_info=True,
        )
        return False
    return True


class StudentModelHook(ModeGatedHook):
    """Run the agent on ``subagent_model`` while the advisor keeps the
    main model.

    Advisor Mode reuses the agent's two existing model slots: the main
    ``active_model`` answers as the teacher and the cheaper
    ``subagent_model`` — when one is configured — runs the agent itself.
    This hook applies the swap by setting ``model_slot_override`` on the
    request before :class:`AgentBuilder` builds the model, the same path a
    spawned subagent uses. An override already present on the request
    (an explicit per-request model) always wins.
    """

    phase = Phase.PRE_AGENT_BUILD
    name = "advisor_mode_student_model"
    priority = 30

    async def _run(self, ctx: HookContext) -> HookResult:
        cfg = resolve_agent_config(ctx)
        state = ctx.mode_state.setdefault("advisor", {})
        state["teacher_model"] = slot_to_dict(effective_teacher_slot(cfg))
        state["student_model"] = None

        student = slot_to_dict(getattr(cfg, "subagent_model", None))
        request = getattr(ctx, "request", None)
        if student is None:
            logger.info(
                "Advisor Mode: no subagent_model configured; the agent "
                "runs on the main model and the advisor shares it",
            )
        elif request is None or _has_model_override(request):
            logger.debug(
                "Advisor Mode: request already carries a model override; "
                "leaving it alone",
            )
        elif _apply_model_override(request, student):
            state["student_model"] = student
            logger.info(
                "Advisor Mode: agent runs on %s:%s (teacher: %s)",
                student["provider_id"],
                student["model"],
                state["teacher_model"],
            )
        return HookResult()


__all__ = ["StudentModelHook"]

# -*- coding: utf-8 -*-
"""Advisor mode hooks."""

from __future__ import annotations

import logging
from typing import Any

from ..base import ModeGatedHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase
from .config import resolve_agent_config
from .models import (
    effective_worker_slot,
    effective_advisor_slot,
    slot_label,
    slot_to_dict,
)

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
            "Advisor Mode: could not set the worker model override",
            exc_info=True,
        )
        return False
    return True


class WorkerModelHook(ModeGatedHook):
    """Run the agent on the worker model while the advisor keeps its own.

    By default Advisor Mode reuses the agent's two existing model slots:
    the main ``active_model`` answers as the advisor and the cheaper
    ``subagent_model`` — when one is configured — runs the agent itself;
    ``advisor_mode.worker_model`` overrides the latter (see
    :func:`effective_worker_slot`). This hook applies the swap by setting
    ``model_slot_override`` on the request before :class:`AgentBuilder`
    builds the model, the same path a spawned subagent uses. An override
    already present on the request (an explicit per-request model) always
    wins.
    """

    phase = Phase.PRE_AGENT_BUILD
    name = "advisor_mode_worker_model"
    priority = 30

    async def _run(self, ctx: HookContext) -> HookResult:
        cfg = resolve_agent_config(ctx)
        worker = slot_to_dict(effective_worker_slot(cfg))
        request = getattr(ctx, "request", None)
        if worker is None:
            logger.info(
                "Advisor Mode: no worker model configured (sub-agent "
                "model or advisor_mode.worker_model); the agent runs on "
                "the main model and the advisor shares it",
            )
        elif request is None or _has_model_override(request):
            logger.debug(
                "Advisor Mode: request already carries a model override; "
                "leaving it alone",
            )
        elif _apply_model_override(request, worker):
            logger.info(
                "Advisor Mode: worker runs on %s:%s (advisor: %s)",
                worker["provider_id"],
                worker["model"],
                slot_label(effective_advisor_slot(cfg)),
            )
        return HookResult()


__all__ = ["WorkerModelHook"]

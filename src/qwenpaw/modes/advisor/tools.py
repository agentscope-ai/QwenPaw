# -*- coding: utf-8 -*-
"""Advisor-mode tools: ``consult_advisor``.

The opening plan is injected as if the agent had called
``consult_advisor``. This module makes that tool real, so the agent can
also ask the advisor on its own (at a decision point, or when it is unsure
whether to abandon a route) instead of waiting for the failure trigger.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator

from agentscope.message import TextBlock
from agentscope.tool import ToolChunk

from .prompts import FALLBACK_ADVICE

if TYPE_CHECKING:
    from .mode import AdvisorMode

logger = logging.getLogger(__name__)

CONSULT_TOOL_NAME = "consult_advisor"
CONSULT_POLICY_NAME = "ConsultAdvisor"

# Part of every model call in Advisor Mode, so kept short.
CONSULT_TOOL_DESCRIPTION = (
    "Ask your advisor (a stronger planning model that already wrote your "
    "plan) when an unresolved judgment affects your next action and the "
    "available evidence is insufficient to choose reliably. If one cheap "
    "tool check can resolve it, do that first. Do not consult for routine "
    "steps. Focus on one decision: include relevant requirements, observed "
    "evidence, attempts and results, options, and the specific uncertainty. "
    "Distinguish facts from assumptions. The advisor cannot run tools or "
    "see your full history. Share only necessary information permitted by "
    "the task's disclosure constraints, preserving conditions and "
    "exceptions that affect the decision. Consultations are capped per "
    "conversation."
)

_NO_SESSION_REPLY = (
    f"The advisor is not available in this session. {FALLBACK_ADVICE}"
)


def register_advisor_tools_governance() -> None:
    """Register ``consult_advisor`` with the governance registry.

    Mode tools are not picked up by the builtin ``@tool_descriptor``
    scan, so ``consult_advisor`` is registered here as an internal tool,
    like Goal mode's ``get_goal``, and the agent can call it without
    approval.
    """
    try:
        from ...governance.tool_registry import (
            DEFAULT_REGISTRY,
            register_tool_governance,
        )

        register_tool_governance(
            DEFAULT_REGISTRY,
            python_name=CONSULT_TOOL_NAME,
            tool_type="internal",
            policy_name=CONSULT_POLICY_NAME,
            owner="builtin",
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "Advisor governance registration skipped",
            exc_info=True,
        )


def _chunk(text: str, block_id: str) -> Any:
    """One streamed piece of the tool result.

    Every chunk carries the same block id, so the toolkit accumulates
    them into a single text block (the agent then reads one reply, not a
    list of fragments) and the UI appends each piece as it arrives.
    """
    return ToolChunk(content=[TextBlock(type="text", text=text, id=block_id)])


def make_consult_advisor(owner: "AdvisorMode") -> Any:
    """Build the ``consult_advisor`` tool function bound to ``owner``.

    The tool is an async generator: the advisor's answer streams into the
    tool result while it is being written, like the injected plan does.
    """

    async def consult_advisor(question: str) -> AsyncIterator[Any]:
        """Ask the advisor about an unresolved decision in the current task.

        Args:
            question: A concise decision or question, with the relevant
                constraints, observed evidence, assumptions, attempts and
                results, and options. Include the specific uncertainty
                you need resolved and only information allowed to be shared.
        """
        block_id = uuid.uuid4().hex[:12]
        middleware = owner.current_middleware()
        if middleware is None:
            logger.info(
                "consult_advisor called without an active advisor session",
            )
            yield _chunk(_NO_SESSION_REPLY, block_id)
            return
        if not middleware.on_demand_enabled:
            yield _chunk(
                "On-demand consultation is switched off for this agent. "
                f"{FALLBACK_ADVICE}",
                block_id,
            )
            return
        async for piece in middleware.consult_stream(question):
            yield _chunk(piece, block_id)

    return consult_advisor


__all__ = [
    "CONSULT_TOOL_DESCRIPTION",
    "CONSULT_TOOL_NAME",
    "make_consult_advisor",
    "register_advisor_tools_governance",
]

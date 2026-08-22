# -*- coding: utf-8 -*-
"""Advisor-mode tools: ``consult_advisor``.

The opening plan and the automatic mid-run interventions are injected
*as if* the agent had called ``consult_advisor``. This module makes that
tool real, so the agent can also ask the advisor on its own — at a
decision point, or when it is unsure whether to abandon a route — instead
of waiting for the failure trigger.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .mode import AdvisorMode

logger = logging.getLogger(__name__)

CONSULT_TOOL_NAME = "consult_advisor"
CONSULT_POLICY_NAME = "ConsultAdvisor"

# Keep this short: it is part of every model call in Advisor Mode. The
# "when" matters more than the "how" — over-use burns the budget, under-use
# leaves the advisor idle.
CONSULT_TOOL_DESCRIPTION = (
    "Ask your advisor (a stronger planning model that already wrote your "
    "plan) for strategic guidance. Use it at a real decision point, before "
    "committing to a costly or irreversible route, or when you are unsure "
    "whether to abandon an approach that keeps failing. Do not use it for "
    "routine steps or things you can check yourself with your tools. The "
    "advisor cannot see your files or run code; state what you tried and "
    "what you are deciding between. Limited to a few consultations per "
    "conversation."
)

_NO_SESSION_REPLY = (
    "The advisor is not available in this session. Decide with your own "
    "best judgment and keep going."
)


def register_advisor_tools_governance() -> None:
    """Register ``consult_advisor`` with the governance registry.

    Mode tools are not picked up by the builtin ``@tool_descriptor``
    scan, and an unregistered tool is denied by policy ("'ConsultAdvisor'
    is denied by policy"). Registering it as an *internal* tool lets the
    agent call it without approval, like Goal mode's ``get_goal``.
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


def make_consult_advisor(owner: "AdvisorMode") -> Any:
    """Build the ``consult_advisor`` tool function bound to ``owner``."""

    async def consult_advisor(question: str) -> str:
        """Ask the advisor a strategic question about the current task.

        Args:
            question: What you are deciding or stuck on, in one or two
                sentences, including what you already tried and which
                options you see. Ask about strategy, not syntax.
        """
        middleware = owner.current_middleware()
        if middleware is None:
            logger.info(
                "consult_advisor called without an active advisor session",
            )
            return _NO_SESSION_REPLY
        if not middleware.on_demand_enabled:
            return (
                "On-demand consultation is switched off for this agent. "
                "Decide with your own best judgment and keep going."
            )
        return await middleware.consult(question)

    return consult_advisor


__all__ = [
    "CONSULT_POLICY_NAME",
    "CONSULT_TOOL_DESCRIPTION",
    "CONSULT_TOOL_NAME",
    "make_consult_advisor",
    "register_advisor_tools_governance",
]

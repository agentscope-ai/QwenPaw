# -*- coding: utf-8 -*-
"""Pre-acting hook that guards tool parameters before execution.

This hook integrates with AgentScope's ``pre_acting`` hook point to
scan every tool call's parameters before the tool is invoked.  It
**never blocks** the call – it only logs warnings when suspicious
patterns are detected.

Usage::

    from copaw.security.tool_guard.hook import ToolGuardHook

    hook = ToolGuardHook()
    agent.register_instance_hook(
        hook_type="pre_acting",
        hook_name="tool_guard",
        hook=hook,
    )
"""
from __future__ import annotations

import logging
from typing import Any

from .engine import get_guard_engine

logger = logging.getLogger(__name__)


class ToolGuardHook:
    """AgentScope ``pre_acting`` hook that guards tool-call parameters.

    The hook inspects the :class:`ToolUseBlock` passed into ``_acting``
    and runs the :class:`ToolGuardEngine` against it.  Findings are
    logged as warnings – the tool call is **never** blocked.

    Parameters
    ----------
    engine:
        Explicit engine instance.  When *None* (the default), the
        module-level lazy singleton is used.
    """

    def __init__(self, engine=None) -> None:
        self._engine = engine

    @property
    def engine(self):
        if self._engine is None:
            return get_guard_engine()
        return self._engine

    # ------------------------------------------------------------------
    # Hook callable  (async to match AgentScope's convention)
    # ------------------------------------------------------------------

    async def __call__(
        self,
        agent,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Guard the tool call described by *kwargs* before execution.

        Parameters
        ----------
        agent:
            The agent instance (unused, but required by hook interface).
        kwargs:
            Keyword arguments to ``_acting``.  Expected to contain a
            ``tool_call`` key whose value is a ``ToolUseBlock`` dict
            with ``name`` and ``input`` fields.

        Returns
        -------
        None
            The hook never modifies kwargs – it only logs warnings.
        """
        try:
            tool_call = kwargs.get("tool_call")
            if tool_call is None:
                return None

            # ToolUseBlock is a TypedDict / dict with "name", "input", etc.
            tool_name: str = tool_call.get("name", "")
            tool_input: dict[str, Any] = tool_call.get("input", {})

            if not tool_name:
                return None

            result = self.engine.guard(tool_name, tool_input)
            if result is None:
                # Guarding disabled
                return None

            if result.findings:
                _log_findings(tool_name, result)

        except Exception as exc:  # pragma: no cover
            # Never let guard failures disrupt the agent
            logger.debug(
                "Tool guard hook encountered an error (non-blocking): %s", exc
            )

        # Always return None – never modify kwargs, never block
        return None


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _log_findings(tool_name: str, result) -> None:
    """Emit structured warning logs for each finding."""
    from .models import GuardSeverity

    for finding in result.findings:
        # Choose log level based on severity
        if finding.severity in (GuardSeverity.CRITICAL, GuardSeverity.HIGH):
            log_fn = logger.warning
        else:
            log_fn = logger.info

        log_fn(
            "[TOOL GUARD] %s | tool=%s param=%s rule=%s | %s | matched=%r",
            finding.severity.value,
            tool_name,
            finding.param_name or "*",
            finding.rule_id,
            finding.description,
            finding.matched_value,
        )

    # Summary line
    logger.warning(
        "[TOOL GUARD] Summary for tool '%s': %d finding(s), "
        "max_severity=%s, duration=%.3fs. "
        "Execution NOT blocked.",
        tool_name,
        result.findings_count,
        result.max_severity.value,
        result.guard_duration_seconds,
    )

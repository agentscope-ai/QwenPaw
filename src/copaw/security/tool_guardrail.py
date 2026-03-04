# -*- coding: utf-8 -*-
"""
Security guarding integration for CoPaw tool-call lifecycle.

Provides a thin API that the agent/hook layer calls **before** a tool
function is executed.  The scanner checks the tool name and parameters
against a set of security rules and reports dangerous patterns.

* **pre-tool-call** – before an agent invokes any tool, the hook calls
  :func:`guard_tool_call` to scan parameters for risky patterns
  (command injection, data exfiltration, sensitive file access, …).

By design the guard **never blocks** execution – it only emits
warnings via the logging framework.  This can be changed in the future
by toggling ``COPAW_TOOL_GUARD_BLOCK``.

The guard engine itself is lazily instantiated so that import-time is
near-zero.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from .tool_guard.engine import get_guard_engine

if TYPE_CHECKING:
    from .tool_guard.models import ToolGuardResult  # noqa: F401 – type-only

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment-variable knobs
# ---------------------------------------------------------------------------
#  COPAW_TOOL_GUARD_ENABLED  – "true" (default) / "false"
#  COPAW_TOOL_GUARD_BLOCK    – "false" (default) / "true"
#                               When True, unsafe tool calls will raise
#                               ToolGuardError.  When False (default),
#                               only a warning is logged.

_TRUE_STRINGS = {"true", "1", "yes"}


def _guard_enabled() -> bool:
    return os.environ.get("COPAW_TOOL_GUARD_ENABLED", "true").lower() in _TRUE_STRINGS


def _guard_blocks() -> bool:
    return os.environ.get("COPAW_TOOL_GUARD_BLOCK", "false").lower() in _TRUE_STRINGS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ToolGuardError(Exception):
    """Raised when a tool call fails a security guard and blocking is enabled."""

    def __init__(self, result: "ToolGuardResult") -> None:
        self.result = result
        findings_summary = "; ".join(
            f"[{f.severity.value}] {f.title} (rule: {f.rule_id})"
            for f in result.findings[:5]
        )
        truncated = (
            f" (and {len(result.findings) - 5} more)"
            if len(result.findings) > 5
            else ""
        )
        super().__init__(
            f"Tool guard for '{result.tool_name}' found "
            f"{len(result.findings)} issue(s) "
            f"(max severity: {result.max_severity.value}): "
            f"{findings_summary}{truncated}"
        )


def guard_tool_call(
    tool_name: str,
    params: dict[str, Any],
    *,
    block: bool | None = None,
) -> "ToolGuardResult | None":
    """Guard a tool call and optionally block on unsafe results.

    Parameters
    ----------
    tool_name:
        Name of the tool about to be called.
    params:
        Keyword arguments that will be passed to the tool function.
    block:
        Whether to raise :class:`ToolGuardError` when the guard finds
        CRITICAL/HIGH issues.  *None* means use the
        ``COPAW_TOOL_GUARD_BLOCK`` env var (default: ``false``).

    Returns
    -------
    ToolGuardResult or None
        ``None`` when guarding is disabled.

    Raises
    ------
    ToolGuardError
        When blocking is enabled and the tool call is deemed unsafe.
    """
    if not _guard_enabled():
        return None

    engine = get_guard_engine()
    result = engine.guard(tool_name, params)

    if result is not None and not result.is_safe:
        should_block = block if block is not None else _guard_blocks()
        if should_block:
            raise ToolGuardError(result)
        logger.warning(
            "Tool '%s' has %d security finding(s) (max severity: %s) "
            "but blocking is disabled – proceeding anyway.",
            result.tool_name,
            len(result.findings),
            result.max_severity.value,
        )

    return result

# -*- coding: utf-8 -*-
"""Tool-guard utility helpers.

* Configuration resolution – which tools to guard and which to deny.
* Structured logging for guard findings.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterable

from ...constant import EnvVarLoader

if TYPE_CHECKING:
    from .models import ToolGuardResult

logger = logging.getLogger(__name__)

_DEFAULT_GUARDED_TOOLS = frozenset(
    {
        "execute_shell_command",
        "read_file",
        "write_file",
        "edit_file",
        "append_file",
        "send_file_to_user",
        "view_text_file",
        "write_text_file",
    },
)


def _parse_guarded_tokens(tokens: Iterable[str]) -> set[str] | None:
    """Parse guarded tool tokens into scope set.

    ``None`` means guard all tools.
    """
    normalized = {item.strip() for item in tokens if item and item.strip()}
    if not normalized:
        return set()

    lowered = {item.lower() for item in normalized}
    if "*" in lowered or "all" in lowered:
        return None
    if lowered.issubset({"none", "off", "false", "0"}):
        return set()

    return normalized


def _load_config_tool_guard():
    """Load ``ToolGuardConfig`` from config.json via the Pydantic model.

    Returns ``None`` when config cannot be loaded.
    """
    try:
        from copaw.config import load_config

        return load_config().security.tool_guard
    except Exception:
        return None


def resolve_guarded_tools(
    user_defined: set[str] | list[str] | tuple[str, ...] | None = None,
) -> set[str] | None:
    """Resolve guarded tools set.

    Priority:
    1) constructor-provided ``user_defined``
    2) ``QWENPAW_TOOL_GUARD_TOOLS`` env var
    3) ``config.json`` -> ``security.tool_guard.guarded_tools``
    4) built-in high-risk default set

    Returns
    -------
    set[str] | None
        ``None`` means guard all tools.
    """
    if user_defined is not None:
        return _parse_guarded_tokens(user_defined)

    raw = EnvVarLoader.get_str("QWENPAW_TOOL_GUARD_TOOLS") or None
    if raw is not None:
        normalized = raw.strip().lower()
        if normalized in {"*", "all"}:
            return None
        if normalized in {"", "none", "off", "false", "0"}:
            return set()
        return _parse_guarded_tokens(raw.split(","))

    cfg = _load_config_tool_guard()
    if cfg is not None and cfg.guarded_tools is not None:
        return _parse_guarded_tokens(cfg.guarded_tools)

    return set(_DEFAULT_GUARDED_TOOLS)


def resolve_denied_tools(
    user_defined: set[str] | list[str] | tuple[str, ...] | None = None,
) -> set[str]:
    """Resolve the set of tools that are unconditionally denied.

    Priority:
    1) constructor-provided ``user_defined``
    2) ``QWENPAW_TOOL_GUARD_DENIED_TOOLS`` env var (comma-separated)
    3) ``config.json`` -> ``security.tool_guard.denied_tools``
    4) built-in default (empty)

    Returns
    -------
    set[str]
        Tool names that must be auto-rejected without user approval.
    """
    if user_defined is not None:
        return set(user_defined)

    raw = EnvVarLoader.get_str("QWENPAW_TOOL_GUARD_DENIED_TOOLS") or None
    if raw is not None:
        return {t.strip() for t in raw.split(",") if t.strip()}

    cfg = _load_config_tool_guard()
    if cfg is not None and cfg.denied_tools:
        return set(cfg.denied_tools)

    return set()


def log_findings(tool_name: str, result: "ToolGuardResult") -> None:
    """Emit structured logs for each finding."""
    from .models import GuardSeverity

    _HIGH_SEVERITIES = (GuardSeverity.CRITICAL, GuardSeverity.HIGH)

    for finding in result.findings:
        if finding.severity in _HIGH_SEVERITIES:
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

    summary_fn = (
        logger.warning
        if result.max_severity in _HIGH_SEVERITIES
        else logger.info
    )
    summary_fn(
        "[TOOL GUARD] Summary for tool '%s': %d finding(s), "
        "max_severity=%s, duration=%.3fs",
        tool_name,
        result.findings_count,
        result.max_severity.value,
        result.guard_duration_seconds,
    )

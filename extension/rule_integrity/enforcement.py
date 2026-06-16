# -*- coding: utf-8 -*-
"""Fail-closed enforcement when built-in rule integrity is compromised."""
from __future__ import annotations

import logging
import time
from typing import Any

from .constants import MAX_CONSECUTIVE_TIMEOUT_RETRIES
from .verifier import get_last_rule_integrity_status

logger = logging.getLogger(__name__)

_LOCKDOWN_STATUSES = frozenset({"tampered", "check_failed"})
_AUTO_REPAIR_SUCCESS_DISPLAY_SECONDS = 10.0

_auto_repair_in_progress = False
_auto_repair_completed_until: float | None = None
_auto_repair_timeout_retry = 0
_auto_repair_abandoned = False


def rule_integrity_lockdown_active() -> bool:
    """Return True when built-in rules are untrusted and tools must be blocked."""

    status = get_last_rule_integrity_status()
    if status.ok or status.status == "unknown":
        return False
    return status.status in _LOCKDOWN_STATUSES


def auto_repair_abandoned() -> bool:
    return _auto_repair_abandoned


def mark_auto_repair_started() -> None:
    global _auto_repair_in_progress, _auto_repair_abandoned, _auto_repair_timeout_retry

    _auto_repair_abandoned = False
    _auto_repair_timeout_retry = 0
    _auto_repair_in_progress = True


def mark_auto_repair_timeout_retry(retry_count: int) -> None:
    global _auto_repair_timeout_retry

    _auto_repair_timeout_retry = max(
        0,
        min(int(retry_count), MAX_CONSECUTIVE_TIMEOUT_RETRIES),
    )


def mark_auto_repair_abandoned() -> None:
    global _auto_repair_abandoned, _auto_repair_in_progress, _auto_repair_timeout_retry

    _auto_repair_abandoned = True
    _auto_repair_in_progress = False
    _auto_repair_timeout_retry = MAX_CONSECUTIVE_TIMEOUT_RETRIES


def mark_auto_repair_finished(*, succeeded: bool) -> None:
    global _auto_repair_in_progress, _auto_repair_completed_until
    global _auto_repair_timeout_retry, _auto_repair_abandoned

    _auto_repair_in_progress = False
    if succeeded:
        _auto_repair_abandoned = False
        _auto_repair_timeout_retry = 0
        _auto_repair_completed_until = (
            time.monotonic() + _AUTO_REPAIR_SUCCESS_DISPLAY_SECONDS
        )


def tick_auto_repair_display() -> None:
    """Clear the transient success banner after its display window."""

    global _auto_repair_completed_until

    if _auto_repair_completed_until is None:
        return
    if time.monotonic() >= _auto_repair_completed_until:
        _auto_repair_completed_until = None


def get_enforcement_projection() -> dict[str, Any]:
    tick_auto_repair_display()
    lockdown = rule_integrity_lockdown_active()
    completed = (
        _auto_repair_completed_until is not None
        and time.monotonic() < _auto_repair_completed_until
    )
    return {
        "rules_disabled": lockdown,
        "auto_repair_in_progress": _auto_repair_in_progress,
        "auto_repair_completed": completed and not lockdown,
        "auto_repair_timeout_retry": _auto_repair_timeout_retry,
        "auto_repair_abandoned": _auto_repair_abandoned,
        "auto_repair_timeout_max": MAX_CONSECUTIVE_TIMEOUT_RETRIES,
    }


def reload_tool_guard_engine_rules() -> None:
    """Reload guardians after a successful rule integrity repair."""

    try:
        from qwenpaw.security.tool_guard.engine import get_guard_engine

        get_guard_engine().reload_rules()
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Failed to reload tool guard engine after rule integrity repair",
            exc_info=True,
        )

# -*- coding: utf-8 -*-
"""Driver-local time helpers for policy evaluation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config import load_config
from ..config.timezone import normalize_tz

logger = logging.getLogger(__name__)


def current_policy_time() -> datetime:
    """Return now in the configured user timezone for Driver policy checks."""
    try:
        configured = getattr(load_config(), "user_timezone", "") or ""
        timezone_name = normalize_tz(str(configured)) or "UTC"
        return datetime.now(ZoneInfo(timezone_name))
    except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
        logger.debug(
            "Invalid configured timezone for Driver policy; "
            "falling back to UTC",
            exc_info=exc,
        )
    except Exception as exc:  # pragma: no cover - defensive config fallback
        logger.debug(
            "Failed to load configured timezone for Driver policy; "
            "falling back to UTC",
            exc_info=exc,
        )
    return datetime.now(timezone.utc)

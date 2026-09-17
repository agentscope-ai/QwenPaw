# -*- coding: utf-8 -*-
"""Browser trace event recording (minimal logging scaffold)."""

from __future__ import annotations

import logging
from typing import Any

from ...utils.logging import sanitize_log_value

logger = logging.getLogger(__name__)


def record_browser_trace_event(*args: Any, **kwargs: Any) -> None:
    """Record a browser trace event without affecting the caller."""
    logger.debug(
        "browser-trace args=%s kwargs=%s",
        sanitize_log_value(args),
        sanitize_log_value(kwargs),
    )


__all__ = ["record_browser_trace_event"]

# -*- coding: utf-8 -*-
"""Single host entry for optional security extension hooks."""
from __future__ import annotations

from .file_baseline_bridge import (
    get_integrity_settings_projection,
    get_file_baseline_service,
    notify_file_saved,
    run_startup_scan_if_enabled,
    stream_file_baseline_events,
)
from .rule_integrity_bridge import (
    run_rule_integrity_startup_check,
    stream_rule_integrity_events,
)

__all__ = [
    "get_integrity_settings_projection",
    "get_file_baseline_service",
    "notify_file_saved",
    "run_startup_scan_if_enabled",
    "run_rule_integrity_startup_check",
    "stream_file_baseline_events",
    "stream_rule_integrity_events",
]

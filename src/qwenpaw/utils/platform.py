# -*- coding: utf-8 -*-
"""Platform-specific utility helpers."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def is_windows_admin() -> bool:
    """Return True if the current Windows process has admin privileges.

    On non-Windows platforms, returns True (not relevant, guard is a no-op).
    When admin detection fails, returns False (conservative: assume not admin).
    """
    if sys.platform != "win32":
        return True  # non-Windows: not relevant
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def warn_unelevated_sandbox() -> None:
    """Log a warning when sandbox runs in unelevated mode.

    The unelevated sandbox can still run without admin privileges, but
    offers weaker isolation than the elevated sandbox.  Log a warning so
    the user knows about the reduced protection.

    The config file is NOT modified — this is a runtime-only notice so the
    user's intent is preserved.

    Called once during startup (both ``qwenpaw app`` and the Tauri backend).
    On non-Windows platforms or when already elevated, this is a no-op.
    """
    if sys.platform != "win32":
        return

    if is_windows_admin():
        return  # admin: sandbox can work normally

    # Not admin: check if sandbox is configured on.
    try:
        from ..config import load_config

        config = load_config()
        if config.security.sandbox_enabled:
            logger.warning(
                "Windows sandbox downgraded to unelevated mode: the sandbox "
                "is enabled but QwenPaw is not running as administrator. "
                "The unelevated sandbox provides limited isolation. For "
                "full sandbox protection, close QwenPaw and relaunch it "
                "with 'Run as administrator'.",
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Windows unelevated sandbox check failed; continuing as-is.",
            exc_info=True,
        )

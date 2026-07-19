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


def auto_disable_sandbox_on_windows() -> None:
    """Log a warning when sandbox is enabled but process lacks admin.

    The restricted-token sandbox requires administrator privileges to
    set up filesystem ACLs and launch sandboxed processes.  If the user
    has ``security.sandbox_enabled=true`` but the current process is not
    elevated, log a warning so the user knows why the sandbox won't
    activate this session.

    The config file is NOT modified — this is a runtime-only downgrade so the
    user's intent is preserved for future admin launches.

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
                "Windows sandbox downgraded for this session: administrator "
                "privileges are required for the sandbox, but QwenPaw is not "
                "running as administrator. The sandbox will be inactive for "
                "this session. To use the sandbox, close QwenPaw and relaunch "
                "it with 'Run as administrator'.",
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Windows sandbox auto-disable check failed; continuing as-is.",
            exc_info=True,
        )

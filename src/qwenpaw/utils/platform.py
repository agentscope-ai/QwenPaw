# -*- coding: utf-8 -*-
"""Platform-specific utility helpers."""
from __future__ import annotations

import logging
import os
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


def repair_windows_data_dir_permissions() -> None:
    """One-time repair for directories left with admin-only ACLs.

    PR #5931 introduced UAC elevation that ran QwenPaw as admin.  The elevated
    process may have created or modified files/directories under ~/.qwenpaw
    with restrictive ACLs that block the normal (non-admin) user.  This
    function detects the issue by testing write access, and if denied, runs
    ``icacls /reset /t`` to restore inherited permissions.

    Called once at startup on Windows when NOT running as admin.
    Idempotent: if permissions are fine, this is a fast no-op.
    """
    if sys.platform != "win32":
        return

    if is_windows_admin():
        return  # admin: no permission issue possible

    try:
        from ..constant import WORKING_DIR
    except Exception:  # noqa: BLE001
        return

    data_dir = str(WORKING_DIR)
    if not os.path.isdir(data_dir):
        return

    # Quick probe: can we create a temp file in the data directory?
    probe_path = os.path.join(data_dir, ".qwenpaw_permission_probe")
    try:
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write("probe")
        os.unlink(probe_path)
        return  # writable: nothing to fix
    except PermissionError:
        pass  # need repair
    except OSError:
        return  # non-permission error, don't interfere

    # Repair: reset ACLs to inherited defaults via icacls.
    logger.warning(
        "Detected broken permissions on %s (likely left by a previous "
        "admin-elevated session). Attempting automatic repair via icacls...",
        data_dir,
    )
    try:
        import subprocess

        result = subprocess.run(
            ["icacls", data_dir, "/reset", "/t", "/q"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            logger.info(
                "Successfully repaired permissions on %s",
                data_dir,
            )
        else:
            logger.warning(
                "icacls returned code %d. stdout=%s stderr=%s. "
                "You may need to manually run: "
                'icacls "%s" /reset /t /q',
                result.returncode,
                result.stdout.strip(),
                result.stderr.strip(),
                data_dir,
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Automatic permission repair failed. Please run manually:\n"
            '  icacls "%s" /reset /t /q',
            data_dir,
            exc_info=True,
        )

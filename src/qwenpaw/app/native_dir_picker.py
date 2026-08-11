# -*- coding: utf-8 -*-
"""Open the operating system's own folder-chooser and return its result.

Why this exists at all: a browser deliberately withholds absolute paths.
``<input type="file" webkitdirectory>`` and ``showDirectoryPicker()`` both
open the native chooser, but hand JavaScript only a directory *handle* and
names relative to the chosen folder — never where it lives on disk. Binding
a project directory needs the absolute path, so the browser cannot supply
it no matter which API is used.

The console's backend, however, runs on the user's own machine, so it can
open the dialog itself and read the answer. The window appears on the same
display the user is looking at.

That is only true for a **local** install, which is why every entry point
here is guarded as localhost-only by the router. On a remote or headless
host the dialog would either pop up on the wrong screen or hang, so
:func:`native_picker_available` reports False there and callers fall back
to the in-app directory browser.

Desktop (Tauri) builds do not use this module at all — they call the
dialog plugin directly in-process.
"""
from __future__ import annotations

import logging
import shutil
import sys
from typing import Optional, Sequence

from ..utils.command_runner import CommandExecutionError, run_command_async

logger = logging.getLogger(__name__)

# Generous: the timer runs while the user browses their filesystem, and a
# premature kill would close the dialog under their cursor. This only
# bounds a hung/never-answered dialog.
_DIALOG_TIMEOUT_S = 600

# AppleScript returns error -128 when the user presses Cancel. Anything
# else is a real failure worth surfacing.
_APPLESCRIPT_USER_CANCELLED = -128

_MACOS_SCRIPT = """\
try
    set chosen to choose folder with prompt "{prompt}"
    return POSIX path of chosen
on error number -128
    return ""
end try
"""

# -STA is required: FolderBrowserDialog is a COM/WinForms control and
# raises in the default MTA apartment PowerShell uses for -Command.
_WINDOWS_SCRIPT = """\
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '{prompt}'
$dialog.ShowNewFolderButton = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::Out.Write($dialog.SelectedPath)
}}
"""


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _escape_powershell_single(text: str) -> str:
    return text.replace("'", "''")


def _windows_shell() -> Optional[str]:
    """Prefer PowerShell 7 but accept the one that ships with Windows."""
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _linux_command(prompt: str) -> Optional[Sequence[str]]:
    zenity = shutil.which("zenity")
    if zenity:
        return [
            zenity,
            "--file-selection",
            "--directory",
            f"--title={prompt}",
        ]
    kdialog = shutil.which("kdialog")
    if kdialog:
        return [kdialog, "--getexistingdirectory", "."]
    return None


def _has_display() -> bool:
    """Best-effort check that a GUI session exists on Linux.

    Without this a headless server would block on a dialog nobody can see
    until the timeout expires.
    """
    import os

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def native_picker_available() -> bool:
    """Return True when this host can show a folder dialog."""
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None
    if sys.platform in ("win32", "cygwin"):
        return _windows_shell() is not None
    return _has_display() and _linux_command("") is not None


def _build_command(prompt: str) -> Optional[Sequence[str]]:
    if sys.platform == "darwin":
        osascript = shutil.which("osascript")
        if not osascript:
            return None
        script = _MACOS_SCRIPT.format(prompt=_escape_applescript(prompt))
        return [osascript, "-e", script]
    if sys.platform in ("win32", "cygwin"):
        shell = _windows_shell()
        if not shell:
            return None
        script = _WINDOWS_SCRIPT.format(
            prompt=_escape_powershell_single(prompt),
        )
        return [shell, "-NoProfile", "-STA", "-Command", script]
    if not _has_display():
        return None
    return _linux_command(prompt)


async def pick_directory(
    prompt: str = "Select a project folder",
) -> Optional[str]:
    """Show the OS folder chooser; return the chosen path.

    Returns ``None`` when the user cancels — a normal outcome, not an
    error. Raises :class:`RuntimeError` when no dialog can be shown or the
    helper process fails, so the caller can degrade to the in-app browser
    instead of silently doing nothing.
    """
    command = _build_command(prompt)
    if command is None:
        raise RuntimeError("No native folder dialog is available on this host")

    try:
        result = await run_command_async(
            command,
            timeout=_DIALOG_TIMEOUT_S,
            encoding="utf-8",
            # zenity/kdialog exit non-zero on Cancel, and so does osascript
            # for unhandled errors; inspect the code ourselves.
            check=False,
        )
    except CommandExecutionError as exc:
        raise RuntimeError(f"Folder dialog failed: {exc}") from exc

    chosen = (result.stdout or "").strip()
    if result.returncode != 0:
        # Cancel: zenity=1, kdialog=1, PowerShell writes nothing. Treat a
        # non-zero exit with no output as a cancel rather than an error,
        # because that is overwhelmingly what it means here.
        if not chosen:
            logger.debug("Folder dialog cancelled (rc=%s)", result.returncode)
            return None
        raise RuntimeError(
            f"Folder dialog failed (rc={result.returncode}): "
            f"{(result.stderr or '').strip()[:200]}",
        )

    if not chosen:
        return None
    # AppleScript's POSIX path keeps a trailing slash for folders; strip it
    # so the value matches what every other code path produces.
    if len(chosen) > 1:
        chosen = chosen.rstrip("/")
    return chosen


__all__ = ["native_picker_available", "pick_directory"]

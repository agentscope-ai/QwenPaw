# -*- coding: utf-8 -*-
# pylint:disable=unused-import
"""
Desktop Dev entry: same as gui_launcher but tee stdout/stderr to a log file
and install excepthooks so crashes leave a trace in support-dir/logs/.
Shared by scripts/pack/; entry point uses import gui_launcher (no . relative).
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path


# Set COPAW_WORKING_DIR before any copaw import (same logic as gui_launcher).
def _desktop_support_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(base) / "CoPaw"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CoPaw"
    return Path.home() / ".copaw"


_SUPPORT = _desktop_support_dir().resolve()
os.environ["COPAW_WORKING_DIR"] = str(_SUPPORT)

# Force PyInstaller to bundle reme (import is optional at runtime for dev).
try:
    import reme  # noqa: F401
except ImportError:
    pass

_LOG_DIR = _SUPPORT / "logs"
_LOG_FILE = _LOG_DIR / "copaw_dev.log"
_ORIG_STDOUT = sys.__stdout__
_ORIG_STDERR = sys.__stderr__
_LOG_HANDLE = None


class _Tee:
    """Write to both original stream and log file (for crash persistence)."""

    def __init__(self, stream, log_handle):
        self._stream = stream
        self._log = log_handle

    def write(self, data):
        try:
            self._stream.write(data)
            self._stream.flush()
        except (OSError, ValueError):
            pass
        try:
            if self._log and not self._log.closed:
                self._log.write(data)
                self._log.flush()
        except (OSError, ValueError):
            pass

    def flush(self):
        try:
            self._stream.flush()
        except (OSError, ValueError):
            pass
        try:
            if self._log and not self._log.closed:
                self._log.flush()
        except (OSError, ValueError):
            pass

    def fileno(self):
        return self._stream.fileno()

    def isatty(self):
        return getattr(self._stream, "isatty", lambda: False)()


def _install_log_tee() -> None:
    global _LOG_HANDLE
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        # pylint: disable=consider-using-with
        _LOG_HANDLE = _LOG_FILE.open("a", encoding="utf-8")
        sys.stdout = _Tee(_ORIG_STDOUT, _LOG_HANDLE)
        sys.stderr = _Tee(_ORIG_STDERR, _LOG_HANDLE)
    except OSError:
        pass


def _log_crash(msg: str) -> None:
    try:
        _ORIG_STDERR.write(msg)
        _ORIG_STDERR.flush()
    except (OSError, ValueError):
        pass
    try:
        if _LOG_HANDLE and not _LOG_HANDLE.closed:
            _LOG_HANDLE.write(msg)
            _LOG_HANDLE.flush()
    except (OSError, ValueError):
        pass


def _excepthook(typ, value, tb):
    _log_crash("\n--- CoPaw-Dev uncaught exception ---\n")
    _log_crash("".join(traceback.format_exception(typ, value, tb)))
    _log_crash(f"Log file: {_LOG_FILE}\n")
    if sys.__excepthook__ is not _excepthook:
        sys.__excepthook__(typ, value, tb)


def _thread_excepthook(args):
    _log_crash("\n--- CoPaw-Dev thread exception ---\n")
    if args.exc_type is not None and args.exc_value is not None:
        _log_crash(
            "".join(
                traceback.format_exception(
                    args.exc_type,
                    args.exc_value,
                    args.exc_traceback,
                ),
            ),
        )
    _log_crash(f"Log file: {_LOG_FILE}\n")


def main() -> None:
    _install_log_tee()
    sys.excepthook = _excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook
    import gui_launcher  # noqa: E402

    gui_launcher.main()


if __name__ == "__main__":
    main()

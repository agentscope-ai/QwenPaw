# -*- coding: utf-8 -*-
"""Log capture for the Tauri Python sidecar runtime."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
import faulthandler
import logging
import os
from pathlib import Path
import platform
import sys
from typing import TextIO

_LOG_FILE: TextIO | None = None


class _TeeStream:
    """Minimal text stream tee for Python stdout/stderr.

    This wrapper is intentionally limited to text output. Low-level writes
    through the underlying file descriptor are not intercepted.
    """

    def __init__(self, primary: TextIO, secondary: TextIO) -> None:
        self._primary = primary
        self._secondary = secondary
        self.encoding = getattr(primary, "encoding", "utf-8")
        self.errors = getattr(primary, "errors", "replace")

    def write(self, data: str) -> int:
        self._primary.write(data)
        self._secondary.write(data)
        return len(data)

    def flush(self) -> None:
        self._primary.flush()
        self._secondary.flush()

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._primary.fileno()

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


def install_sidecar_logging(log_path: Path) -> Path:
    """Mirror early sidecar output to a file and enable native crash traces."""
    log_path = Path(log_path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    global _LOG_FILE  # pylint: disable=global-statement
    _LOG_FILE = log_path.open(  # pylint: disable=consider-using-with
        "a",
        encoding="utf-8",
        errors="replace",
        buffering=1,
    )
    _LOG_FILE.write("\n")
    _LOG_FILE.write(
        f"== qwenpaw tauri sidecar {datetime.now().isoformat()} ==\n",
    )
    _LOG_FILE.write(f"platform={platform.platform()}\n")
    _LOG_FILE.write(f"python={sys.executable}\n")
    _LOG_FILE.write(f"argv={sys.argv!r}\n")
    _LOG_FILE.write(f"cwd={os.getcwd()}\n")
    _LOG_FILE.flush()

    sys.stdout = _TeeStream(sys.stdout, _LOG_FILE)  # type: ignore[assignment]
    sys.stderr = _TeeStream(sys.stderr, _LOG_FILE)  # type: ignore[assignment]
    faulthandler.enable(file=_LOG_FILE, all_threads=True)
    _add_project_file_handler(log_path)
    logging.getLogger("qwenpaw.tauri").info(
        "Tauri sidecar logging enabled: %s",
        log_path,
    )
    return log_path


def _add_project_file_handler(log_path: Path) -> None:
    # Import lazily so qwenpaw.constant is loaded only after desktop env setup.
    from qwenpaw.utils.logging import add_project_file_handler

    add_project_file_handler(log_path)

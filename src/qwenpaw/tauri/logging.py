# -*- coding: utf-8 -*-
"""Log capture for the Tauri Python sidecar runtime."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
import faulthandler
import logging
import logging.handlers
import os
from pathlib import Path
import platform
import sys
from typing import TextIO

from qwenpaw.desktop_env import DESKTOP_BACKEND_LOG_ENV, DESKTOP_PORT_ENV

_LOG_FILE: TextIO | None = None
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


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


def install_sidecar_logging() -> Path | None:
    """Mirror early sidecar output to a file and enable native crash traces."""
    raw_path = os.environ.get(DESKTOP_BACKEND_LOG_ENV)
    if not raw_path:
        return None

    log_path = Path(raw_path).expanduser()
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
    _LOG_FILE.write(f"port={os.environ.get(DESKTOP_PORT_ENV, '')}\n")
    _LOG_FILE.flush()

    sys.stdout = _TeeStream(sys.stdout, _LOG_FILE)  # type: ignore[assignment]
    sys.stderr = _TeeStream(sys.stderr, _LOG_FILE)  # type: ignore[assignment]
    faulthandler.enable(file=_LOG_FILE, all_threads=True)
    _add_logging_handler(log_path)
    logging.getLogger("qwenpaw.tauri").info(
        "Tauri sidecar logging enabled: %s",
        log_path,
    )
    return log_path


def _add_logging_handler(log_path: Path) -> None:
    logger = logging.getLogger("qwenpaw")
    resolved = log_path.resolve()
    for handler in logger.handlers:
        base = getattr(handler, "baseFilename", None)
        if base is not None and Path(base).resolve() == resolved:
            return

    handler = logging.handlers.RotatingFileHandler(
        resolved,
        encoding="utf-8",
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        ),
    )
    handler.setLevel(logger.level or logging.INFO)
    logger.addHandler(handler)

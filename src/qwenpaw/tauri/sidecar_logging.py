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
from typing import Protocol, TextIO, cast

_CRASH_LOG_FILE: TextIO | None = None


class _RotatingTextHandler(Protocol):
    encoding: str | None

    def write_text(self, text: str) -> int:
        raise NotImplementedError

    def flush(self) -> None:
        raise NotImplementedError


class _RotatingTextStream:
    def __init__(self, handler: _RotatingTextHandler) -> None:
        self._handler = handler

    def write(self, data: str) -> int:
        encoding = self._handler.encoding or "utf-8"
        safe_text = data.encode(encoding, errors="replace").decode(encoding)
        return self._handler.write_text(safe_text)

    def flush(self) -> None:
        self._handler.flush()


class _TeeStream:
    """Minimal text stream tee for Python stdout/stderr.

    This wrapper is intentionally limited to text output. Low-level writes
    through the underlying file descriptor are not intercepted.
    """

    def __init__(
        self,
        primary: TextIO,
        secondary: TextIO | _RotatingTextStream,
    ) -> None:
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

    handler = _add_project_file_handler(log_path)
    log_stream = _RotatingTextStream(handler)
    log_stream.write("\n")
    log_stream.write(
        f"== qwenpaw tauri sidecar {datetime.now().isoformat()} ==\n",
    )
    log_stream.write(f"platform={platform.platform()}\n")
    log_stream.write(f"python={sys.executable}\n")
    log_stream.write(f"argv={sys.argv!r}\n")
    log_stream.write(f"cwd={os.getcwd()}\n")

    crash_log_path = log_path.with_name("desktop-crash.log")
    rotation_error: PermissionError | None = None
    try:
        _rotate_previous_crash_log(crash_log_path)
    except PermissionError as exc:
        rotation_error = exc
    global _CRASH_LOG_FILE  # pylint: disable=global-statement
    _CRASH_LOG_FILE = (
        crash_log_path.open(  # pylint: disable=consider-using-with
            "a",
            encoding="utf-8",
            errors="replace",
            buffering=1,
        )
    )
    faulthandler.enable(file=_CRASH_LOG_FILE, all_threads=True)
    sys.stdout = _TeeStream(sys.stdout, log_stream)  # type: ignore[assignment]
    sys.stderr = _TeeStream(sys.stderr, log_stream)  # type: ignore[assignment]
    logging.getLogger("qwenpaw.tauri").info(
        "Tauri sidecar logging enabled: %s",
        log_path,
    )
    if rotation_error is not None:
        logging.getLogger("qwenpaw.tauri").warning(
            "Could not rotate previous crash logs; appending to %s: %s",
            crash_log_path,
            rotation_error,
        )
    return log_path


def _add_project_file_handler(log_path: Path) -> _RotatingTextHandler:
    # Import lazily so qwenpaw.constant is loaded only after desktop env setup.
    from qwenpaw.utils.logging import add_project_file_handler

    add_project_file_handler(log_path)
    resolved_path = str(log_path.resolve())
    for handler in logging.getLogger("qwenpaw").handlers:
        if getattr(handler, "baseFilename", None) == resolved_path:
            if not callable(getattr(handler, "write_text", None)):
                raise TypeError(
                    f"Handler for {log_path} cannot write raw text"
                )
            return cast(_RotatingTextHandler, handler)
    raise RuntimeError(f"No rotating log handler found for {log_path}")


def _rotate_previous_crash_log(log_path: Path) -> None:
    from qwenpaw.utils.logging import _resolve_log_rotation_settings

    _, backup_count = _resolve_log_rotation_settings()
    if backup_count == 0:
        log_path.unlink(missing_ok=True)
        return

    for index in range(backup_count, 0, -1):
        source = log_path if index == 1 else Path(f"{log_path}.{index - 1}")
        destination = Path(f"{log_path}.{index}")
        if source.exists():
            source.replace(destination)

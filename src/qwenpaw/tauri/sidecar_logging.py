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

_LOG_FILE: _HandlerStream | None = None
_CRASH_FD: int | None = None


class _HandlerStream:
    """Text stream that appends raw output through a file handler's stream.

    Sharing the handler's stream keeps a single open handle on the log file,
    so the handler can still rotate it (Windows refuses to rename a file
    while another handle is open).
    """

    def __init__(self, handler: logging.FileHandler) -> None:
        self._handler = handler

    def write(self, data: str) -> int:
        handler = self._handler
        handler.acquire()
        try:
            self._rollover_if_needed(len(data))
            if handler.stream is None:
                # pylint: disable-next=protected-access
                handler.stream = handler._open()
            stream = handler.stream
            try:
                stream.write(data)
            except UnicodeEncodeError:
                encoding = stream.encoding or "utf-8"
                stream.write(
                    data.encode(encoding, "replace").decode(encoding),
                )
            stream.flush()
        except Exception:  # noqa: BLE001 - mirroring must not break stdio
            pass
        finally:
            handler.release()
        return len(data)

    def _rollover_if_needed(self, incoming: int) -> None:
        handler = self._handler
        max_bytes = getattr(handler, "maxBytes", 0)
        if max_bytes <= 0 or handler.stream is None:
            return
        handler.stream.seek(0, os.SEEK_END)
        size = handler.stream.tell()
        if size and size + incoming >= max_bytes:
            handler.doRollover()  # type: ignore[attr-defined]

    def flush(self) -> None:
        # write() flushes eagerly, matching the old line-buffered file.
        return None


class _TeeStream:
    """Minimal text stream tee for Python stdout/stderr.

    This wrapper is intentionally limited to text output. Low-level writes
    through the underlying file descriptor are not intercepted.
    """

    def __init__(
        self,
        primary: TextIO,
        secondary: TextIO | _HandlerStream,
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
    """Mirror sidecar output to a rotating log and enable native crash traces.

    Python logging records and raw stdout/stderr text share one rotating file
    handler for ``log_path``. faulthandler holds its file descriptor for the
    whole process lifetime, so native crash traces go to a separate
    ``<name>-crash<suffix>`` file that only rotates here, at startup.
    """
    log_path = Path(log_path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    global _LOG_FILE, _CRASH_FD  # pylint: disable=global-statement
    _LOG_FILE = _HandlerStream(_add_project_file_handler(log_path))
    started = datetime.now().isoformat()
    _LOG_FILE.write("\n")
    _LOG_FILE.write(f"== qwenpaw tauri sidecar {started} ==\n")
    _LOG_FILE.write(f"platform={platform.platform()}\n")
    _LOG_FILE.write(f"python={sys.executable}\n")
    _LOG_FILE.write(f"argv={sys.argv!r}\n")
    _LOG_FILE.write(f"cwd={os.getcwd()}\n")

    sys.stdout = _TeeStream(sys.stdout, _LOG_FILE)  # type: ignore[assignment]
    sys.stderr = _TeeStream(sys.stderr, _LOG_FILE)  # type: ignore[assignment]

    crash_path = log_path.with_name(f"{log_path.stem}-crash{log_path.suffix}")
    # Writing the header through a rotating handler rotates an oversized
    # crash log. The handler is released right away: logging reconfiguration
    # (e.g. uvicorn's dictConfig) closes every handler ever created, so
    # faulthandler gets a raw descriptor that logging does not own.
    crash_handler = _create_rotating_file_handler(crash_path)
    try:
        _HandlerStream(crash_handler).write(
            f"== qwenpaw tauri sidecar {started} pid={os.getpid()} ==\n",
        )
    finally:
        crash_handler.close()
    _CRASH_FD = os.open(crash_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    faulthandler.enable(file=_CRASH_FD, all_threads=True)

    logging.getLogger("qwenpaw.tauri").info(
        "Tauri sidecar logging enabled: %s (native crash traces: %s)",
        log_path,
        crash_path,
    )
    return log_path


def _add_project_file_handler(log_path: Path) -> logging.FileHandler:
    # Import lazily so qwenpaw.constant is loaded only after desktop env setup.
    from qwenpaw.utils.logging import add_project_file_handler

    return add_project_file_handler(log_path)


def _create_rotating_file_handler(log_path: Path) -> logging.FileHandler:
    from qwenpaw.utils.logging import create_rotating_file_handler

    return create_rotating_file_handler(log_path)

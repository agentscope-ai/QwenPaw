# -*- coding: utf-8 -*-
"""Single-backend reconciliation for the Tauri desktop sidecar.

The desktop shell starts the Python backend as a sidecar and kills it on a
graceful exit. But on a crash, OOM, force-quit, or ``SIGKILL`` the exit
handler never runs, so the backend is orphaned. The next launch then starts
a fresh backend on top of the orphan, and repeated cycles accumulate many
~500 MB backends (issue #5550).

Before a new backend binds its port it calls
:func:`reconcile_singleton_backend`, which terminates the backend recorded
by the previous launch (verified to actually be a QwenPaw backend, to guard
against PID reuse) and then records its own PID. This makes "one desktop
backend at a time" hold even across abnormal termination.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

PID_FILENAME = "desktop_backend.pid"

# How long to wait for a terminated backend to exit before SIGKILL.
_TERMINATE_TIMEOUT_SECONDS = 5.0

_BACKEND_CMDLINE_MARKERS = (
    "qwenpaw.tauri.entry",
    "qwenpaw-backend",
)


def _read_recorded_pid(pid_file: Path) -> Optional[int]:
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        pid = int(text)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _looks_like_backend(proc: psutil.Process) -> bool:
    """Best-effort check that *proc* is a QwenPaw desktop backend.

    Guards against PID reuse: a recorded PID may have been recycled by an
    unrelated process, which must never be killed.
    """
    try:
        name = (proc.name() or "").lower()
    except (psutil.Error, OSError):
        name = ""
    if "qwenpaw-backend" in name:
        return True
    try:
        exe = (proc.exe() or "").lower()
    except (psutil.Error, OSError):
        exe = ""
    if "qwenpaw-backend" in exe:
        return True
    try:
        cmdline = " ".join(proc.cmdline()).lower()
    except (psutil.Error, OSError):
        cmdline = ""
    return any(marker in cmdline for marker in _BACKEND_CMDLINE_MARKERS)


def _terminate_previous_backend(pid_file: Path) -> None:
    pid = _read_recorded_pid(pid_file)
    if pid is None or pid == os.getpid():
        return

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    except psutil.Error:
        logger.debug("Could not inspect recorded backend pid %s", pid)
        return

    if not _looks_like_backend(proc):
        logger.info(
            "Recorded backend pid %s is not a QwenPaw backend "
            "(likely PID reuse); leaving it alone",
            pid,
        )
        return

    logger.info("Terminating orphaned QwenPaw backend pid %s", pid)
    try:
        proc.terminate()
        try:
            proc.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)
        except psutil.TimeoutExpired:
            logger.warning(
                "Orphaned backend pid %s did not exit; killing it",
                pid,
            )
            proc.kill()
    except psutil.NoSuchProcess:
        pass
    except psutil.Error:
        logger.warning(
            "Failed to terminate orphaned backend pid %s",
            pid,
            exc_info=True,
        )


def _write_pid(pid_file: Path, pid: int) -> None:
    # Single writer at startup; a torn read is self-healing because
    # _read_recorded_pid treats a non-integer file as "no pid".
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid), encoding="utf-8")


def reconcile_singleton_backend(working_dir: "str | os.PathLike[str]") -> None:
    """Kill a leftover backend from a prior launch, then record this one.

    Never raises: a failure here must not block backend startup.
    """
    pid_file = Path(working_dir) / PID_FILENAME
    try:
        _terminate_previous_backend(pid_file)
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Backend reconciliation (terminate) failed",
            exc_info=True,
        )
    try:
        _write_pid(pid_file, os.getpid())
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Backend reconciliation (record pid) failed",
            exc_info=True,
        )

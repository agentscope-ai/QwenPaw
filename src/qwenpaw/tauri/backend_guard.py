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

That reconciliation used to assume the previous *desktop* process was gone.
It is not always: launching the app a second time while an instance is
already running starts a second backend, whose reconciliation then killed
the first instance's still-in-use backend and left that window broken
(issue #8000). Each backend now also records the process that spawned it,
and a backend whose spawner is still alive is treated as in use rather than
orphaned.
"""

from __future__ import annotations

import json
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


def _valid_pid(value: object) -> Optional[int]:
    """Coerce *value* to a positive PID, or ``None``."""
    try:
        pid = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _parse_recorded_pids(text: str) -> tuple[Optional[int], Optional[int]]:
    """Parse a pid-file body into ``(backend_pid, owner_pid)``.

    Accepts the JSON form written today and the bare-integer form written by
    older builds; the latter carries no owner, so the second element is
    ``None`` and the caller falls back to the legacy behaviour.
    """
    text = text.strip()
    if not text:
        return None, None

    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError:
            return None, None
        if not isinstance(payload, dict):
            return None, None
        return _valid_pid(payload.get("pid")), _valid_pid(payload.get("ppid"))

    return _valid_pid(text), None


def _read_recorded_pids(pid_file: Path) -> tuple[Optional[int], Optional[int]]:
    try:
        text = pid_file.read_text(encoding="utf-8")
    except OSError:
        return None, None
    return _parse_recorded_pids(text)


def _read_recorded_pid(pid_file: Path) -> Optional[int]:
    return _read_recorded_pids(pid_file)[0]


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


def _owner_is_live(owner_pid: Optional[int]) -> bool:
    """Whether the process that spawned the recorded backend still runs.

    A live spawner means a live desktop instance still owns that backend, so
    it is in use rather than orphaned. When the owner is gone the backend is
    exactly the leak :func:`reconcile_singleton_backend` exists to reap.
    """
    if owner_pid is None or owner_pid == os.getpid():
        return False
    try:
        proc = psutil.Process(owner_pid)
        if not proc.is_running():
            return False
        # A reaped-but-not-yet-collected spawner is not an owner either.
        return proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.Error, OSError):
        return False


def _terminate_previous_backend(pid_file: Path) -> None:
    pid, owner_pid = _read_recorded_pids(pid_file)
    if pid is None or pid == os.getpid():
        return

    if _owner_is_live(owner_pid):
        logger.info(
            "Recorded backend pid %s is still owned by live process %s; "
            "another desktop instance is using it, leaving it alone",
            pid,
            owner_pid,
        )
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


def _write_pid(
    pid_file: Path,
    pid: int,
    owner_pid: Optional[int] = None,
) -> None:
    """Record this backend and the process that spawned it.

    ``owner_pid`` is what tells the next launch whether this backend is
    still owned. Older builds wrote a bare integer; that form is still
    accepted on read.
    """
    payload = {"pid": pid}
    if owner_pid is not None and owner_pid > 0 and owner_pid != pid:
        payload["ppid"] = owner_pid
    # Single writer at startup; a torn read is self-healing because
    # _read_recorded_pids treats an unparsable file as "no pid".
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


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
        _write_pid(pid_file, os.getpid(), _spawner_pid())
    except Exception:  # pragma: no cover - defensive
        logger.debug(
            "Backend reconciliation (record pid) failed",
            exc_info=True,
        )


def _spawner_pid() -> Optional[int]:
    """PID of the process that started this backend, when known."""
    try:
        return os.getppid()
    except (AttributeError, OSError):  # pragma: no cover - platform guard
        return None

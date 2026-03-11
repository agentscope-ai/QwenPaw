# -*- coding: utf-8 -*-
"""Helpers for resilient JSON file persistence."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


if os.name == "nt":
    import msvcrt
else:
    import fcntl


logger = logging.getLogger(__name__)


class FileLock(AbstractContextManager["FileLock"]):
    """Cross-process lock backed by a sibling lock file."""

    def __init__(self, path: Path):
        self._path = path
        self._file = None

    def __enter__(self) -> "FileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("a+b")
        if os.name == "nt":
            self._ensure_lock_byte()
        self._acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._release()
        finally:
            if self._file is not None:
                self._file.close()
                self._file = None

    def _acquire(self) -> None:
        assert self._file is not None
        if os.name == "nt":
            while True:
                try:
                    self._file.seek(0)
                    msvcrt.locking(
                        self._file.fileno(),
                        msvcrt.LK_LOCK,
                        1,
                    )
                    return
                except OSError:
                    time.sleep(0.05)
        else:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)

    def _ensure_lock_byte(self) -> None:
        assert self._file is not None
        self._file.seek(0, os.SEEK_END)
        if self._file.tell() == 0:
            self._file.write(b"0")
            self._file.flush()

    def _release(self) -> None:
        if self._file is None:
            return
        if os.name == "nt":
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)


def load_json_with_recovery(
    path: Path,
    *,
    default_payload: Any,
    storage_name: str,
    logger_: logging.Logger | None = None,
) -> Any:
    """Load JSON from disk, auto-recovering empty or malformed files."""
    if logger_ is None:
        logger_ = logger

    with FileLock(_lock_path(path)):
        if not path.exists():
            return default_payload

        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                raise ValueError("file is empty")
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            backup_path = _backup_corrupted_file(path)
            _write_json_unlocked(path, default_payload)
            logger_.warning(
                "Recovered corrupted %s at %s: %s. Backup: %s",
                storage_name,
                path,
                exc,
                backup_path,
            )
            return default_payload


def save_json_atomically(path: Path, payload: Any) -> None:
    """Save JSON payload with cross-process lock and atomic replace."""
    with FileLock(_lock_path(path)):
        _write_json_unlocked(path, payload)


def repair_json_file(
    path: Path,
    *,
    default_payload: Any,
    storage_name: str,
    reason: str,
    logger_: logging.Logger | None = None,
) -> None:
    """Backup and rebuild a JSON file after schema validation failure."""
    if logger_ is None:
        logger_ = logger

    with FileLock(_lock_path(path)):
        if path.exists():
            backup_path = _backup_corrupted_file(path)
            logger_.warning(
                "Recovered corrupted %s at %s: %s. Backup: %s",
                storage_name,
                path,
                reason,
                backup_path,
            )
        _write_json_unlocked(path, default_payload)


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _backup_corrupted_file(path: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = path.suffix or ".json"
    backup_path = path.with_name(
        f"{path.stem}.corrupt.{ts}.{os.getpid()}{suffix}",
    )
    path.replace(backup_path)
    return backup_path


def _write_json_unlocked(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(
                payload,
                tmp_file,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return

    dir_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

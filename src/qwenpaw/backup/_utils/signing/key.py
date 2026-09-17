# -*- coding: utf-8 -*-
"""Signing-key persistence for backup HMACs.

Each installation keeps a private key under BACKUP_DIR. The key is not placed
inside backups; it exists only to decide whether a backup was created or
trusted locally before restore/import applies sensitive files.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
from pathlib import Path

from ....constant import BACKUP_DIR

logger = logging.getLogger(__name__)

_KEY_NAME = ".signing_key"
_KEY_BYTES = 32
_LOCK = threading.Lock()
_cached_key: bytes | None = None
_cached_mtime_ns: int | None = None


def _chmod_best_effort(path: Path, mode: int) -> None:
    """Tighten filesystem permissions where the platform supports it."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _key_file() -> Path:
    return BACKUP_DIR / _KEY_NAME


def _read_key(path: Path) -> tuple[bytes, int] | None:
    """Read and validate the persisted local signing key."""
    if not path.exists():
        return None
    if path.is_symlink():
        raise RuntimeError("refusing to read signing key from symlink")
    raw = path.read_text(encoding="ascii").strip()
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise RuntimeError("invalid backup signing key encoding") from exc
    if len(key) != _KEY_BYTES:
        raise RuntimeError("invalid backup signing key length")
    return key, path.stat().st_mtime_ns


def _create_key_atomic(path: Path) -> tuple[bytes, int]:
    """Create the signing key with exclusive open to avoid key races."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(path.parent, 0o700)
    if path.is_symlink():
        raise RuntimeError("refusing to write key over symlink")

    key = secrets.token_bytes(_KEY_BYTES)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow

    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        existing = _read_key(path)
        if existing is None:
            raise
        return existing

    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(key.hex())
        fh.write("\n")
    _chmod_best_effort(path, 0o600)
    return key, path.stat().st_mtime_ns


def get_signing_key() -> bytes:
    """Return the local backup signing key, creating it when absent.

    The mtime-based cache keeps normal backup operations cheap while still
    noticing manual key rotation between requests.
    """
    global _cached_key, _cached_mtime_ns

    path = _key_file()
    try:
        mtime_ns = path.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = None

    if _cached_key is not None and _cached_mtime_ns == mtime_ns:
        return _cached_key

    with _LOCK:
        try:
            current_mtime_ns = path.stat().st_mtime_ns
        except FileNotFoundError:
            current_mtime_ns = None

        if _cached_key is not None and _cached_mtime_ns == current_mtime_ns:
            return _cached_key

        if current_mtime_ns is None:
            key, new_mtime_ns = _create_key_atomic(path)
        else:
            key, new_mtime_ns = _read_key(path)  # type: ignore[misc]
            if _cached_key is not None and _cached_mtime_ns != new_mtime_ns:
                logger.warning(
                    "Signing key was rotated; pre-rotation backups will "
                    "require trust_mode=foreign on restore.",
                )

        _cached_key = key
        _cached_mtime_ns = new_mtime_ns
        return key

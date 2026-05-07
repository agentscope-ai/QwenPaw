# -*- coding: utf-8 -*-
"""Crash-safe directory swap utilities for backup restore operations.

Three-phase protocol:
  Phase 1 – Extract into a sibling ``.restore_tmp`` directory.
  Phase 2 – Atomically rename old dst → ``.restore_old``, then tmp → dst.
  Phase 3 – Remove ``.restore_old`` (old data is now disposable).

A mid-restore crash never leaves *dst* in a broken state: either the old
content is intact or the new content is complete.

Important: do NOT place files that must be preserved inside *dst* before
calling ``extract_to_tmp`` + ``commit_tmp``.  Phase 2/3 replaces the entire
directory tree, so anything written inside *dst* beforehand will be lost.

Two-phase transactional usage
------------------------------
For restoring multiple directories atomically (so a failure in one target
does not leave others already committed), use the split API::

    # Stage all targets first:
    tmp_paths = []
    for (zf, prefix, dst, zip_slip_base) in targets:
        tmp_paths.append(extract_to_tmp(zf, prefix, dst, zip_slip_base))

    # Commit only when all extractions succeeded:
    for dst in dsts:
        commit_tmp(dst)

On any extraction failure, call ``discard_tmp(dst)`` for each staged dst
to clean up.

Thread safety
-------------
Each *dst* path is protected by a per-path ``threading.Lock`` so that
concurrent callers cannot interleave their extract / commit / discard
operations for the same destination.  The lock is held for the duration of
the entire phase-1, phase-2+3, or cleanup operation.
"""
from __future__ import annotations

import logging
import shutil
import threading
import zipfile
from pathlib import Path

from ._mount_swap import (
    prepare_destination_for_swap,
    recover_mount_point_swap,
    should_skip_zip_member,
)

logger = logging.getLogger(__name__)

_RESTORE_TMP_SUFFIX = ".restore_tmp"
_RESTORE_OLD_SUFFIX = ".restore_old"

# Per-destination threading locks.  The dict itself is guarded by _LOCKS_GUARD.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(dst: Path) -> threading.Lock:
    """Return (and lazily create) a per-destination ``threading.Lock``."""
    key = str(dst.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def cleanup_stale_restore_artifacts(base_dir: Path) -> None:
    """Remove ``.restore_tmp`` / ``.restore_old`` directories left by a
    previous crashed restore.  Must be called before starting a new
    safe-swap for *base_dir*.

    Three scenarios are handled:

    1. ``.restore_old`` exists, ``base_dir`` does NOT exist
       → crash between the two renames in phase 2.  Rename .restore_old
         back to recover original data, then remove any orphaned .restore_tmp.

    2. ``.restore_tmp`` exists, ``base_dir`` exists
       → crash during phase 1 (extraction); drop the incomplete tmp dir.

    3. ``.restore_old`` exists, ``base_dir`` exists
       → crash during phase 3 (rmtree of old); drop the obsolete old dir.
    """
    with _lock_for(base_dir):
        _cleanup_stale_restore_artifacts_locked(base_dir)


def _startup_restore_targets() -> list[Path]:
    """Return restore targets that may be loaded during app startup."""
    from ...config import load_config
    from ...config.utils import get_config_path
    from ...constant import SECRET_DIR, WORKING_DIR

    targets = [
        SECRET_DIR,
        WORKING_DIR / "skill_pool",
    ]
    config = load_config(get_config_path())
    for profile in config.agents.profiles.values():
        targets.append(Path(profile.workspace_dir).expanduser())
    return _dedupe_paths(targets)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path.absolute())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def cleanup_startup_restore_artifacts() -> None:
    """Recover interrupted restores before startup reads restored content."""
    for target in _startup_restore_targets():
        cleanup_stale_restore_artifacts(target)


def _cleanup_stale_restore_artifacts_locked(base_dir: Path) -> None:
    """Implementation of cleanup_stale_restore_artifacts (caller holds
    lock)."""
    tmp = base_dir.with_name(base_dir.name + _RESTORE_TMP_SUFFIX)
    old = base_dir.with_name(base_dir.name + _RESTORE_OLD_SUFFIX)

    # Scenario 1: original data saved in .restore_old; recover it first.
    if old.exists() and not base_dir.exists():
        try:
            old.rename(base_dir)
            logger.warning(
                "Recovered %s from stale %s artifact",
                base_dir,
                _RESTORE_OLD_SUFFIX,
            )
        except OSError:
            logger.exception(
                "Failed to recover %s from %s",
                base_dir,
                _RESTORE_OLD_SUFFIX,
            )
            # Keep .restore_old intact to avoid data loss; abort cleanup.
            return

    # Scenario 2: incomplete extraction.
    if tmp.exists():
        try:
            shutil.rmtree(tmp)
            logger.warning(
                "Removed stale %s artifact: %s",
                _RESTORE_TMP_SUFFIX,
                tmp,
            )
        except OSError:
            logger.exception(
                "Failed to remove stale %s %s",
                _RESTORE_TMP_SUFFIX,
                tmp,
            )

    # Scenario 3: interrupted cleanup.
    if old.exists():
        try:
            shutil.rmtree(old)
            logger.warning(
                "Removed stale %s artifact: %s",
                _RESTORE_OLD_SUFFIX,
                old,
            )
        except OSError:
            logger.exception(
                "Failed to remove stale %s %s",
                _RESTORE_OLD_SUFFIX,
                old,
            )

    recover_mount_point_swap(
        base_dir,
        base_dir.with_name(base_dir.name + _RESTORE_TMP_SUFFIX),
    )


def _extract_zip_to(
    zf: zipfile.ZipFile,
    prefix: str,
    tmp_dst: Path,
    base_resolved: Path,
) -> None:
    """Phase 1: extract ZIP entries with *prefix* into *tmp_dst*.

    Applies Zip Slip guard: skips any entry whose resolved logical path
    falls outside *base_resolved*.
    """
    for info in zf.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        rel = info.filename[len(prefix) :]

        if should_skip_zip_member(info.filename, prefix):
            continue

        # Zip Slip guard: validate the *logical* destination path.
        if not (base_resolved / rel).resolve().is_relative_to(base_resolved):
            logger.warning(
                "Skipping suspicious path in backup: %s",
                info.filename,
            )
            continue

        target = tmp_dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _swap_directories(dst: Path, tmp_dst: Path, old_dst: Path) -> None:
    """Phase 2: atomically swap *tmp_dst* into *dst* via two renames.

    If the first rename succeeds but the second fails (e.g. permissions,
    Windows open-handle), the original directory is restored from *old_dst*
    before re-raising, so *dst* is never left absent.
    """
    if not tmp_dst.exists():
        raise RuntimeError(
            f"commit_tmp called without a valid staging directory: {tmp_dst}",
        )

    handled, renamed_to_old = prepare_destination_for_swap(
        dst,
        tmp_dst,
        old_dst,
    )
    if handled:
        return

    try:
        tmp_dst.rename(dst)
    except OSError:
        # Roll back: restore original data if we moved it away.
        if renamed_to_old and old_dst.exists() and not dst.exists():
            try:
                old_dst.rename(dst)
                logger.warning(
                    "Rolled back %s rename after failed commit; "
                    "original data restored from %s",
                    dst,
                    old_dst,
                )
            except OSError:
                logger.exception(
                    "Rollback of %s failed — original data is in %s",
                    dst,
                    old_dst,
                )
        raise


def _discard_old(old_dst: Path) -> None:
    """Phase 3: remove the backup of the original directory."""
    if old_dst.exists():
        shutil.rmtree(old_dst)


# ---------------------------------------------------------------------------
# Two-phase transactional API
# ---------------------------------------------------------------------------


def extract_to_tmp(
    zf: zipfile.ZipFile,
    prefix: str,
    dst: Path,
    *,
    zip_slip_base: Path | None = None,
) -> Path:
    """Phase 1 only: extract ZIP entries with *prefix* into a sibling
    ``.restore_tmp`` directory and return its path.

    Call :func:`commit_tmp` to promote the extraction into *dst*, or
    :func:`discard_tmp` to roll it back.

    *zip_slip_base* defaults to *dst* and is used for the Zip Slip guard.
    """
    if zip_slip_base is None:
        zip_slip_base = dst
    base_resolved = zip_slip_base.resolve()

    with _lock_for(dst):
        tmp_dst = dst.with_name(dst.name + _RESTORE_TMP_SUFFIX)
        if tmp_dst.exists():
            shutil.rmtree(tmp_dst)
        tmp_dst.mkdir(parents=True, exist_ok=True)

        _extract_zip_to(zf, prefix, tmp_dst, base_resolved)
        return tmp_dst


def commit_tmp(dst: Path) -> None:
    """Phases 2 + 3: atomically swap the staged ``.restore_tmp`` into *dst*
    and remove the old directory.

    Must be called after a successful :func:`extract_to_tmp` for the same
    *dst*.

    Raises :class:`RuntimeError` if the staging directory does not exist
    (e.g. called twice for the same *dst*).
    """
    with _lock_for(dst):
        tmp_dst = dst.with_name(dst.name + _RESTORE_TMP_SUFFIX)
        old_dst = dst.with_name(dst.name + _RESTORE_OLD_SUFFIX)
        _swap_directories(dst, tmp_dst, old_dst)
        _discard_old(old_dst)


def discard_tmp(dst: Path) -> None:
    """Remove the ``.restore_tmp`` sibling of *dst* if it exists.

    Used during rollback when a multi-target extraction fails part-way.
    """
    with _lock_for(dst):
        tmp_dst = dst.with_name(dst.name + _RESTORE_TMP_SUFFIX)
        if tmp_dst.exists():
            try:
                shutil.rmtree(tmp_dst)
            except OSError:
                logger.exception(
                    "Failed to discard staging directory %s",
                    tmp_dst,
                )

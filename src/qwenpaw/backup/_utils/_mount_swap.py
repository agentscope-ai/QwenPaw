# -*- coding: utf-8 -*-
"""Mount-point fallback for backup restore directory swaps.

The normal restore path renames the destination directory away and then renames
the staged directory into place.  That is the best path for ordinary
directories, but it fails for Docker volume mount points because the OS refuses
to rename the mount directory itself (typically ``EBUSY`` on Linux).

This module keeps the mount directory stable and swaps only its children:

1. ``evacuating_old``: move existing children into ``.qwenpaw_restore_old``.
2. ``installing_new``: move staged children from the sibling ``.restore_tmp``.
3. ``committed``: new contents are live; only cleanup remains.

The state file lets startup cleanup decide whether to roll back to old content
or finish cleanup after a crash.  The fallback is intentionally isolated here
so ``safe_swap.py`` can remain focused on the normal rename protocol.
"""
from __future__ import annotations

import errno
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

OLD_CONTENT_DIR_NAME = ".qwenpaw_restore_old"
STATE_FILE_NAME = ".qwenpaw_restore_state"
STATE_TMP_FILE_NAME = ".qwenpaw_restore_state.tmp"

STATE_EVACUATING_OLD = "evacuating_old"
STATE_INSTALLING_NEW = "installing_new"
STATE_COMMITTED = "committed"

RESERVED_NAMES = frozenset(
    {
        OLD_CONTENT_DIR_NAME,
        STATE_FILE_NAME,
        STATE_TMP_FILE_NAME,
    },
)

_VALID_STATES = frozenset(
    {
        STATE_EVACUATING_OLD,
        STATE_INSTALLING_NEW,
        STATE_COMMITTED,
    },
)


def is_mount_point(path: Path) -> bool:
    """Return True when *path* is a filesystem mount point."""
    try:
        return os.path.ismount(path)
    except OSError:
        return False


def is_rename_blocked(exc: OSError) -> bool:
    """Return True for errors that mean directory rename cannot be used."""
    return exc.errno in (errno.EBUSY, errno.EXDEV)


def should_skip_zip_member(filename: str, prefix: str) -> bool:
    """Return True when a ZIP member would overwrite restore internals."""
    rel_path = filename[len(prefix) :]
    parts = Path(rel_path).parts
    if not parts or parts[0] not in RESERVED_NAMES:
        return False
    logger.warning("Skipping reserved restore path in backup: %s", filename)
    return True


def prepare_destination_for_swap(
    dst: Path,
    tmp_dst: Path,
    old_dst: Path,
) -> tuple[bool, bool]:
    """Prepare *dst* for normal rename swap, or handle mount fallback.

    Returns ``(handled, renamed_to_old)``.  ``handled`` means the mount-point
    content swap already completed and the caller should return.
    """
    if not dst.exists():
        return False, False

    if is_mount_point(dst):
        swap_mount_point_contents(dst, tmp_dst)
        return True, False

    try:
        dst.rename(old_dst)
        return False, True
    except OSError as exc:
        if not is_rename_blocked(exc):
            raise
        logger.debug(
            "Falling back to content swap for non-renamable %s",
            dst,
        )
        swap_mount_point_contents(dst, tmp_dst)
        return True, False


def swap_mount_point_contents(dst: Path, tmp_dst: Path) -> None:
    """Replace mount-point contents without renaming the mount directory."""
    try:
        _swap_mount_point_contents(dst, tmp_dst)
    except Exception:
        logger.exception("Mount-point content swap failed for %s", dst)
        try:
            recover_mount_point_swap(dst, tmp_dst.name.removeprefix(dst.name))
        except Exception:
            logger.exception(
                "Immediate recovery failed after mount-point swap error "
                "for %s",
                dst,
            )
        raise


def _swap_mount_point_contents(dst: Path, tmp_dst: Path) -> None:
    """Implementation of mount-point content swap."""
    old_dir = dst / OLD_CONTENT_DIR_NAME
    _write_state(dst, STATE_EVACUATING_OLD)
    old_dir.mkdir(exist_ok=True)
    _move_children(dst, old_dir, excluded_names=RESERVED_NAMES)

    _write_state(dst, STATE_INSTALLING_NEW)
    _move_children(tmp_dst, dst, excluded_names=RESERVED_NAMES)

    _write_state(dst, STATE_COMMITTED)
    _cleanup_artifacts(dst, tmp_dst)


def recover_mount_point_swap(dst: Path, restore_tmp_suffix: str) -> None:
    """Recover a crashed mount-point fallback swap, if one is present.

    ``committed`` means the new content is already complete, so recovery only
    cleans artifacts.  ``installing_new`` means the new content may be partial,
    so recovery removes partial new children and restores old content.
    ``evacuating_old`` or a missing/invalid state is treated conservatively:
    move back any old children that had already been evacuated.
    """
    old_dir = dst / OLD_CONTENT_DIR_NAME
    marker = dst / STATE_FILE_NAME
    tmp_marker = dst / STATE_TMP_FILE_NAME
    tmp_dst = dst.with_name(dst.name + restore_tmp_suffix)

    if not (old_dir.exists() or marker.exists() or tmp_marker.exists()):
        return

    if old_dir.exists() and not (marker.exists() or tmp_marker.exists()):
        logger.warning(
            "Leaving possible restore content directory untouched because "
            "no restore state marker exists: %s",
            old_dir,
        )
        return

    state = _read_state(dst)
    try:
        if state == STATE_COMMITTED:
            _cleanup_artifacts(dst, tmp_dst)
            logger.warning(
                "Completed cleanup for committed restore of %s",
                dst,
            )
            return

        if state == STATE_INSTALLING_NEW:
            _rollback_installing_new(
                dst,
                tmp_dst,
                old_dir,
                marker,
                tmp_marker,
            )
            return

        _restore_old_content(dst)
        if tmp_dst.exists():
            shutil.rmtree(tmp_dst)
        marker.unlink(missing_ok=True)
        tmp_marker.unlink(missing_ok=True)
        logger.warning(
            "Rolled back interrupted restore preparation for %s",
            dst,
        )
    except Exception:
        logger.exception(
            "Failed to recover mount-point restore artifacts for %s "
            "(state=%r, old_dir=%s, tmp_dir=%s)",
            dst,
            state,
            old_dir,
            tmp_dst,
        )
        raise


def _rollback_installing_new(
    dst: Path,
    tmp_dst: Path,
    old_dir: Path,
    marker: Path,
    tmp_marker: Path,
) -> None:
    restored = False
    if old_dir.exists():
        _remove_children(dst, excluded_names=RESERVED_NAMES)
        _restore_old_content(dst)
        restored = True
    else:
        logger.error(
            "Cannot roll back partial restore of %s: %s is missing",
            dst,
            old_dir,
        )

    if tmp_dst.exists():
        shutil.rmtree(tmp_dst)
    marker.unlink(missing_ok=True)
    tmp_marker.unlink(missing_ok=True)
    if restored:
        logger.warning("Rolled back partial restore of %s", dst)


def _write_state(dst: Path, state: str) -> None:
    marker = dst / STATE_FILE_NAME
    tmp_marker = dst / STATE_TMP_FILE_NAME
    try:
        tmp_marker.write_text(state, encoding="utf-8")
        with open(tmp_marker, "r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp_marker, marker)

        try:
            fd = os.open(dst, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
    except OSError as exc:
        logger.error(
            "Failed to write restore state %r for %s via %s: %s",
            state,
            dst,
            tmp_marker,
            exc,
        )
        raise


def _read_state(dst: Path) -> str | None:
    marker = dst / STATE_FILE_NAME
    try:
        state = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        if marker.exists():
            logger.warning(
                "Could not read restore state from %s: %s",
                marker,
                exc,
            )
        return None
    if state in _VALID_STATES:
        return state
    logger.warning("Ignoring unknown restore state %r in %s", state, marker)
    return None


def _cleanup_artifacts(dst: Path, tmp_dst: Path) -> None:
    old_dir = dst / OLD_CONTENT_DIR_NAME
    if old_dir.exists():
        shutil.rmtree(old_dir)
    if tmp_dst.exists():
        shutil.rmtree(tmp_dst)
    (dst / STATE_TMP_FILE_NAME).unlink(missing_ok=True)
    (dst / STATE_FILE_NAME).unlink(missing_ok=True)


def _restore_old_content(dst: Path) -> None:
    old_dir = dst / OLD_CONTENT_DIR_NAME
    if old_dir.exists():
        _move_children(old_dir, dst)
        shutil.rmtree(old_dir)


def _move_children(
    src: Path,
    dst: Path,
    *,
    excluded_names: frozenset[str] = frozenset(),
) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for child in list(src.iterdir()):
        if child.name in excluded_names:
            continue
        shutil.move(str(child), str(dst / child.name))


def _remove_children(
    path: Path,
    *,
    excluded_names: frozenset[str] = frozenset(),
) -> None:
    if not path.exists():
        return
    for child in list(path.iterdir()):
        if child.name in excluded_names:
            continue
        _remove_path(child)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)

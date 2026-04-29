# -*- coding: utf-8 -*-
"""Tests for backup restore directory swapping."""
from __future__ import annotations

import errno
import io
import shutil
import uuid
import zipfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.backup._utils._mount_swap import (
    OLD_CONTENT_DIR_NAME,
    RESERVED_NAMES,
    STATE_COMMITTED,
    STATE_EVACUATING_OLD,
    STATE_FILE_NAME,
    STATE_INSTALLING_NEW,
    STATE_TMP_FILE_NAME,
)
from qwenpaw.backup._utils import _mount_swap
from qwenpaw.backup._utils.safe_swap import (
    cleanup_stale_restore_artifacts,
    commit_tmp,
    extract_to_tmp,
)

_RESTORE_TMP_SUFFIX = ".restore_tmp"


def _make_zip(entries: dict[str, str]) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    buffer.seek(0)
    return zipfile.ZipFile(buffer, "r")


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _tmp_dir(dst: Path) -> Path:
    return dst.with_name(dst.name + _RESTORE_TMP_SUFFIX)


@pytest.fixture(name="work_tmp_path")
def _work_tmp_path() -> Iterator[Path]:
    root = Path.cwd() / ".safe_swap_test_tmp"
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


def test_normal_directory_uses_rename_swap(work_tmp_path: Path) -> None:
    dst = work_tmp_path / "secrets"
    dst.mkdir()
    (dst / "old.txt").write_text("old", encoding="utf-8")

    zf = _make_zip({"data/secrets/new.txt": "new"})
    with patch(
        "qwenpaw.backup._utils._mount_swap.is_mount_point",
        return_value=False,
    ), patch(
        "qwenpaw.backup._utils._mount_swap.swap_mount_point_contents",
    ) as mount_swap:
        extract_to_tmp(zf, "data/secrets/", dst, zip_slip_base=dst)
        commit_tmp(dst)

    mount_swap.assert_not_called()
    assert _snapshot(dst) == {"new.txt": "new"}
    assert not _tmp_dir(dst).exists()
    assert not dst.with_name("secrets.restore_old").exists()


def test_mount_point_swap_replaces_contents(work_tmp_path: Path) -> None:
    dst = work_tmp_path / "secrets"
    dst.mkdir()
    (dst / "old.txt").write_text("old", encoding="utf-8")
    (dst / "nested").mkdir()
    (dst / "nested" / "old.txt").write_text("old nested", encoding="utf-8")

    zf = _make_zip(
        {
            "data/secrets/new.txt": "new",
            "data/secrets/nested/new.txt": "new nested",
        },
    )
    with patch(
        "qwenpaw.backup._utils._mount_swap.is_mount_point",
        return_value=True,
    ):
        extract_to_tmp(zf, "data/secrets/", dst, zip_slip_base=dst)
        commit_tmp(dst)

    assert _snapshot(dst) == {
        "nested/new.txt": "new nested",
        "new.txt": "new",
    }
    assert not (dst / OLD_CONTENT_DIR_NAME).exists()
    assert not (dst / STATE_FILE_NAME).exists()
    assert not _tmp_dir(dst).exists()


def test_ebusy_rename_falls_back_to_mount_point_swap(
    work_tmp_path: Path,
) -> None:
    dst = work_tmp_path / "secrets"
    dst.mkdir()
    (dst / "old.txt").write_text("old", encoding="utf-8")

    original_rename = Path.rename

    def rename_or_ebusy(self: Path, target: Path) -> Path:
        if self == dst:
            raise OSError(errno.EBUSY, "Device or resource busy")
        return original_rename(self, target)

    zf = _make_zip({"data/secrets/new.txt": "new"})
    with patch(
        "qwenpaw.backup._utils._mount_swap.is_mount_point",
        return_value=False,
    ), patch.object(Path, "rename", rename_or_ebusy):
        extract_to_tmp(zf, "data/secrets/", dst, zip_slip_base=dst)
        commit_tmp(dst)

    assert _snapshot(dst) == {"new.txt": "new"}


def test_mount_point_swap_failure_restores_old_contents(
    work_tmp_path: Path,
) -> None:
    dst = work_tmp_path / "secrets"
    dst.mkdir()
    (dst / "old.txt").write_text("old", encoding="utf-8")

    zf = _make_zip({"data/secrets/new.txt": "new"})
    original_move_children = getattr(_mount_swap, "_move_children")
    move_calls = 0

    def move_or_fail(*args, **kwargs):
        nonlocal move_calls
        move_calls += 1
        if move_calls == 2:
            raise OSError("simulated install failure")
        return original_move_children(*args, **kwargs)

    with patch(
        "qwenpaw.backup._utils._mount_swap.is_mount_point",
        return_value=True,
    ), patch(
        "qwenpaw.backup._utils._mount_swap._move_children",
        move_or_fail,
    ), pytest.raises(
        OSError,
        match="simulated install failure",
    ):
        extract_to_tmp(zf, "data/secrets/", dst, zip_slip_base=dst)
        commit_tmp(dst)

    assert _snapshot(dst) == {"old.txt": "old"}
    assert not (dst / OLD_CONTENT_DIR_NAME).exists()
    assert not (dst / STATE_FILE_NAME).exists()
    assert not _tmp_dir(dst).exists()


def test_cleanup_rolls_back_evacuating_old_state(
    work_tmp_path: Path,
) -> None:
    dst = work_tmp_path / "secrets"
    dst.mkdir()
    old_dir = dst / OLD_CONTENT_DIR_NAME
    old_dir.mkdir()
    (old_dir / "old-a.txt").write_text("old a", encoding="utf-8")
    (dst / "old-b.txt").write_text("old b", encoding="utf-8")
    (dst / STATE_FILE_NAME).write_text(
        STATE_EVACUATING_OLD,
        encoding="utf-8",
    )
    _tmp_dir(dst).mkdir()
    (_tmp_dir(dst) / "new.txt").write_text("new", encoding="utf-8")

    cleanup_stale_restore_artifacts(dst)

    assert _snapshot(dst) == {
        "old-a.txt": "old a",
        "old-b.txt": "old b",
    }
    assert not old_dir.exists()
    assert not _tmp_dir(dst).exists()
    assert not (dst / STATE_FILE_NAME).exists()


def test_cleanup_rolls_back_installing_new_state(
    work_tmp_path: Path,
) -> None:
    dst = work_tmp_path / "secrets"
    dst.mkdir()
    old_dir = dst / OLD_CONTENT_DIR_NAME
    old_dir.mkdir()
    (old_dir / "old.txt").write_text("old", encoding="utf-8")
    (dst / "new-partial.txt").write_text("new", encoding="utf-8")
    (dst / STATE_FILE_NAME).write_text(
        STATE_INSTALLING_NEW,
        encoding="utf-8",
    )
    _tmp_dir(dst).mkdir()
    (_tmp_dir(dst) / "new-rest.txt").write_text("new", encoding="utf-8")

    cleanup_stale_restore_artifacts(dst)

    assert _snapshot(dst) == {"old.txt": "old"}
    assert not old_dir.exists()
    assert not _tmp_dir(dst).exists()
    assert not (dst / STATE_FILE_NAME).exists()


def test_cleanup_finishes_committed_state(work_tmp_path: Path) -> None:
    dst = work_tmp_path / "secrets"
    dst.mkdir()
    old_dir = dst / OLD_CONTENT_DIR_NAME
    old_dir.mkdir()
    (old_dir / "old.txt").write_text("old", encoding="utf-8")
    (dst / "new.txt").write_text("new", encoding="utf-8")
    (dst / STATE_FILE_NAME).write_text(STATE_COMMITTED, encoding="utf-8")
    _tmp_dir(dst).mkdir()

    cleanup_stale_restore_artifacts(dst)
    cleanup_stale_restore_artifacts(dst)

    assert _snapshot(dst) == {"new.txt": "new"}
    assert not old_dir.exists()
    assert not _tmp_dir(dst).exists()
    assert not (dst / STATE_FILE_NAME).exists()


def test_reserved_restore_names_are_not_extracted(
    work_tmp_path: Path,
) -> None:
    dst = work_tmp_path / "secrets"
    dst.mkdir()
    entries = {
        f"data/secrets/{STATE_FILE_NAME}": "state",
        f"data/secrets/{STATE_TMP_FILE_NAME}": "state tmp",
        f"data/secrets/{OLD_CONTENT_DIR_NAME}/payload.txt": "old",
        "data/secrets/legit.txt": "legit",
    }

    zf = _make_zip(entries)
    extract_to_tmp(zf, "data/secrets/", dst, zip_slip_base=dst)

    tmp_dst = _tmp_dir(dst)
    assert _snapshot(tmp_dst) == {"legit.txt": "legit"}
    for reserved_name in RESERVED_NAMES:
        assert not (tmp_dst / reserved_name).exists()

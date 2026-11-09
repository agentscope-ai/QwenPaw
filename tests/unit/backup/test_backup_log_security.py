# -*- coding: utf-8 -*-
"""Sensitive backup paths must not be emitted to logs."""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import pytest

from qwenpaw.backup._ops import create_helpers
from qwenpaw.backup._utils import _mount_swap, safe_swap


@pytest.mark.parametrize("exists", [False, True])
def test_secret_backup_does_not_log_secret_directory(
    tmp_path,
    monkeypatch,
    caplog,
    exists,
):
    secret_dir = tmp_path / "private-customer-secret-store"
    if exists:
        secret_dir.mkdir()
        (secret_dir / "auth.json").write_text("secret-content")
    monkeypatch.setattr(create_helpers, "SECRET_DIR", secret_dir)
    with caplog.at_level(logging.INFO), zipfile.ZipFile(
        io.BytesIO(),
        "w",
    ) as zf:
        assert create_helpers.add_secrets(zf) is True
        assert zf.namelist() == (["data/secrets/auth.json"] if exists else [])
    assert caplog.records
    assert str(secret_dir) not in caplog.text
    assert secret_dir.name not in caplog.text
    assert "secret-content" not in caplog.text


def test_failed_restore_rollback_does_not_log_sensitive_paths(
    tmp_path,
    monkeypatch,
    caplog,
):
    destination = tmp_path / "private-customer-secret-store"
    destination.mkdir()
    (destination / "old.txt").write_text("old")
    staging = destination.with_name(destination.name + ".restore_tmp")
    staging.mkdir()
    (staging / "new.txt").write_text("new")
    old = destination.with_name(destination.name + ".restore_old")
    real_rename = Path.rename

    def fail_commit(path, target):
        if path == staging:
            raise PermissionError(f"Cannot commit {staging}")
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_commit)
    monkeypatch.setattr(_mount_swap, "is_mount_point", lambda _: False)
    with caplog.at_level(logging.WARNING), pytest.raises(PermissionError):
        safe_swap._swap_directories(destination, staging, old)
    assert (destination / "old.txt").read_text() == "old"
    assert not old.exists()
    assert caplog.records
    assert destination.name not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_mount_restore_failure_does_not_log_exception_paths(
    tmp_path,
    monkeypatch,
    caplog,
):
    destination = tmp_path / "private-customer-secret-store"
    destination.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    real_write_text = Path.write_text

    def fail_state_write(path, *args, **kwargs):
        if path.name == _mount_swap.STATE_TMP_FILE_NAME:
            raise PermissionError(f"Cannot write sensitive path {path}")
        return real_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_state_write)
    with caplog.at_level(logging.ERROR), pytest.raises(PermissionError):
        _mount_swap.swap_mount_point_contents(destination, staging)
    assert caplog.records
    assert destination.name not in caplog.text
    assert str(tmp_path) not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert list(destination.iterdir()) == []

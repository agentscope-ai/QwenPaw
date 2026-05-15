# -*- coding: utf-8 -*-
"""Tests for restore target preflight checks."""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.backup._ops import restore
from qwenpaw.backup.models import BackupValidationError


def test_busy_restore_target_reports_user_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "workspace"
    target.mkdir()

    def fake_assert_directory_renamable(_target: Path) -> None:
        raise PermissionError("locked")

    def fake_find_busy_restore_paths(_target: Path) -> list[Path]:
        return [target / "browser"]

    monkeypatch.setattr(
        restore,
        "assert_directory_renamable",
        fake_assert_directory_renamable,
    )
    monkeypatch.setattr(
        restore,
        "find_busy_restore_paths",
        fake_find_busy_restore_paths,
    )

    with pytest.raises(BackupValidationError) as exc_info:
        restore._assert_restore_targets_available([target])

    assert exc_info.value.code == "restore_target_busy"
    assert exc_info.value.details["locked_paths"] == [
        str(target / "browser"),
    ]

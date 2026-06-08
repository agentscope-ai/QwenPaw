# -*- coding: utf-8 -*-
"""Tests for restore target preflight checks."""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.backup._ops import restore
from qwenpaw.backup.models import BackupValidationError
from qwenpaw.config import workspace_paths


def _empty_config() -> SimpleNamespace:
    return SimpleNamespace(agents=SimpleNamespace(profiles={}))


def _patch_managed_dirs(
    monkeypatch: pytest.MonkeyPatch,
    working_dir: Path,
) -> None:
    monkeypatch.setattr(workspace_paths, "WORKING_DIR", working_dir)
    monkeypatch.setattr(
        workspace_paths,
        "CUSTOM_CHANNELS_DIR",
        working_dir / "custom_channels",
    )
    monkeypatch.setattr(workspace_paths, "PLUGINS_DIR", working_dir / "plugins")
    monkeypatch.setattr(workspace_paths, "SECRET_DIR", working_dir / ".secret")
    monkeypatch.setattr(
        workspace_paths,
        "BACKUP_DIR",
        working_dir / ".backups",
    )


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


def test_plan_agent_destinations_allows_custom_workspace_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_managed_dirs(monkeypatch, tmp_path / "working")
    default_workspace_dir = tmp_path / "agent_workspaces"

    dst_map = restore._plan_agent_destinations(
        ["pocpkg"],
        {"pocpkg"},
        _empty_config(),
        restore.RestoreBackupRequest(
            agent_ids=["pocpkg"],
            default_workspace_dir=str(default_workspace_dir),
        ),
    )

    assert dst_map["pocpkg"] == (
        (default_workspace_dir / "pocpkg").resolve(),
        True,
    )


def test_plan_agent_destinations_rejects_custom_channels_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    working_dir = tmp_path / "working"
    _patch_managed_dirs(monkeypatch, working_dir)

    with pytest.raises(BackupValidationError) as exc_info:
        restore._plan_agent_destinations(
            ["pocpkg"],
            {"pocpkg"},
            _empty_config(),
            restore.RestoreBackupRequest(
                agent_ids=["pocpkg"],
                default_workspace_dir=str(working_dir / "custom_channels"),
            ),
        )

    assert exc_info.value.code == "invalid_workspace_restore_target"
    assert exc_info.value.details["protected_name"] == "custom_channels"


def test_plan_agent_destinations_rejects_traversal_agent_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_managed_dirs(monkeypatch, tmp_path / "working")

    with pytest.raises(BackupValidationError) as exc_info:
        restore._plan_agent_destinations(
            [".."],
            {".."},
            _empty_config(),
            restore.RestoreBackupRequest(agent_ids=[".."]),
        )

    assert exc_info.value.code == "invalid_workspace_restore_target"
    assert "not a safe workspace directory name" in exc_info.value.message

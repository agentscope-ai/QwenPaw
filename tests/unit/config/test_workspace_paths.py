# -*- coding: utf-8 -*-
"""Tests for agent workspace path validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.config import workspace_paths


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


def test_validate_agent_workspace_path_allows_external_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    working_dir = tmp_path / "working"
    _patch_managed_dirs(monkeypatch, working_dir)

    workspace = tmp_path / "custom_agents" / "research"

    assert workspace_paths.validate_agent_workspace_path(
        workspace,
    ) == workspace.resolve()


@pytest.mark.parametrize(
    ("protected_name", "relative_path"),
    [
        ("custom_channels", "custom_channels/poc"),
        ("plugins", "plugins/poc"),
        ("secrets", ".secret/poc"),
        ("backups", ".backups/poc"),
        ("skill_pool", "skill_pool/poc"),
    ],
)
def test_validate_agent_workspace_path_rejects_managed_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    protected_name: str,
    relative_path: str,
) -> None:
    working_dir = tmp_path / "working"
    _patch_managed_dirs(monkeypatch, working_dir)

    with pytest.raises(
        workspace_paths.WorkspacePathValidationError,
    ) as exc_info:
        workspace_paths.validate_agent_workspace_path(
            working_dir / relative_path,
        )

    assert exc_info.value.protected_name == protected_name


def test_validate_agent_workspace_path_rejects_working_dir_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    working_dir = tmp_path / "working"
    _patch_managed_dirs(monkeypatch, working_dir)

    with pytest.raises(
        workspace_paths.WorkspacePathValidationError,
    ) as exc_info:
        workspace_paths.validate_agent_workspace_path(working_dir)

    assert exc_info.value.protected_name == "working_dir"

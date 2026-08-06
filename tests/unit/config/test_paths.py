# -*- coding: utf-8 -*-
"""Tests for configuration-owned path resolution."""

from pathlib import Path

from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.config import paths
from qwenpaw.config.paths import resolve_agent_workspace_path


def test_relative_workspace_path_uses_working_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Resolve relative paths independently from the process CWD."""
    working_dir = tmp_path / "qwenpaw"
    process_dir = tmp_path / "process"
    working_dir.mkdir()
    process_dir.mkdir()
    monkeypatch.setattr(paths, "WORKING_DIR", working_dir)
    monkeypatch.chdir(process_dir)

    result = resolve_agent_workspace_path("relative-workspace", "agent")

    assert result == (working_dir / "relative-workspace").resolve()


def test_workspace_uses_configured_working_dir_for_relative_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Workspace construction must use the shared path resolver."""
    working_dir = tmp_path / "qwenpaw"
    process_dir = tmp_path / "process"
    working_dir.mkdir()
    process_dir.mkdir()
    monkeypatch.setattr(paths, "WORKING_DIR", working_dir)
    monkeypatch.chdir(process_dir)

    workspace = Workspace("agent", "relative-workspace")

    assert (
        workspace.workspace_dir
        == (working_dir / "relative-workspace").resolve()
    )

# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "extension"))

from file_baseline.workspace_browse import browse_workspace_protectable_files


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    skills = root / "skills" / "weather"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# weather", encoding="utf-8")
    (root / "SOUL.md").write_text("soul", encoding="utf-8")
    (root / ".hidden").write_text("nope", encoding="utf-8")
    return root


def test_browse_defaults_to_skills(workspace: Path) -> None:
    payload = browse_workspace_protectable_files(
        workspace_dir=workspace,
        agent_id="default",
        relative_path="skills",
    )
    assert payload["default_path"] == "skills"
    assert payload["current_path"] == "skills"
    names = {entry["name"] for entry in payload["entries"]}
    assert "weather" in names
    assert ".hidden" not in names


def test_browse_lists_file_with_relative_path(workspace: Path) -> None:
    payload = browse_workspace_protectable_files(
        workspace_dir=workspace,
        agent_id="default",
        relative_path="skills/weather",
    )
    files = [entry for entry in payload["entries"] if entry["type"] == "file"]
    assert len(files) == 1
    assert files[0]["rel_path"] == "skills/weather/SKILL.md"


def test_browse_rejects_path_traversal(workspace: Path) -> None:
    with pytest.raises(ValueError, match="Invalid browse path"):
        browse_workspace_protectable_files(
            workspace_dir=workspace,
            agent_id="default",
            relative_path="../etc",
        )


def test_browse_missing_directory_raises(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError):
        browse_workspace_protectable_files(
            workspace_dir=workspace,
            agent_id="default",
            relative_path="missing",
        )


def test_browse_falls_back_when_skills_missing(tmp_path: Path) -> None:
    root = tmp_path / "empty-ws"
    root.mkdir()
    payload = browse_workspace_protectable_files(
        workspace_dir=root,
        agent_id="default",
        relative_path="skills",
    )
    assert payload["default_path"] == ""
    assert payload["current_path"] == ""

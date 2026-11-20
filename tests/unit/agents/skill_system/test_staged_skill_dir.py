# -*- coding: utf-8 -*-
"""Regression coverage for staged skill writes."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from qwenpaw.agents.skill_system.store import (
    _SKILL_STAGE_PREFIX,
    cleanup_orphan_skill_stages,
    is_ignored_skill_entry,
    staged_skill_dir,
)
from qwenpaw.exceptions import SkillsError


def test_staged_skill_dir_uses_explicit_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace" / "skills"
    root.mkdir(parents=True)

    with staged_skill_dir("demo_skill", root_dir=root) as staged:
        staged_root = staged.parent
        assert staged_root.parent == root
        assert staged_root.name.startswith(_SKILL_STAGE_PREFIX)
        assert staged.name == "demo_skill"
        staged.mkdir()
        (staged / "SKILL.md").write_text("demo", encoding="utf-8")

    assert not staged_root.exists()


def test_staged_skill_dir_creates_missing_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace" / "skills"

    with staged_skill_dir("demo_skill", root_dir=root) as staged:
        assert staged.parent.parent == root
        assert staged.parent.is_dir()


def test_staged_skill_dir_rejects_unsafe_skill_name(
    tmp_path: Path,
) -> None:
    with pytest.raises(SkillsError):
        with staged_skill_dir("../escape", root_dir=tmp_path):
            pass


def test_is_ignored_skill_entry_skips_stage_dirs() -> None:
    assert is_ignored_skill_entry(f"{_SKILL_STAGE_PREFIX}stale") is True
    assert is_ignored_skill_entry("real-skill") is False


def test_cleanup_orphan_skill_stages_scans_workspaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "agent"
    skills = workspace / "skills"
    skills.mkdir(parents=True)
    orphan = skills / f"{_SKILL_STAGE_PREFIX}stale"
    (orphan / "demo").mkdir(parents=True)
    system_temp = tmp_path / "system-temp"
    system_temp.mkdir()

    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.registry.list_workspaces",
        lambda: [{"workspace_dir": str(workspace)}],
    )
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(system_temp))

    assert cleanup_orphan_skill_stages(max_age_seconds=-1) == 1
    assert not orphan.exists()

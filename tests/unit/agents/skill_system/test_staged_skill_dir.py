# -*- coding: utf-8 -*-
"""Regression coverage for staged skill writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.agents.skill_system.store import (
    _SKILL_STAGE_PREFIX,
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

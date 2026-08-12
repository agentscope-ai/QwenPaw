# -*- coding: utf-8 -*-
"""Tests for nested workspace skill discovery and resolution."""

from __future__ import annotations

from pathlib import Path

from qwenpaw.agents.skill_system.registry import (
    reconcile_workspace_manifest,
    resolve_effective_skills,
)
from qwenpaw.agents.skill_system.store import (
    discover_workspace_skill_dirs,
    resolve_workspace_skill_dir,
)
from qwenpaw.agents.skill_system.workspace_service import SkillService


def _write_skill(skill_dir: Path, *, name: str, description: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "---\n\n"
            f"# {name}\n"
        ),
        encoding="utf-8",
    )


def test_discover_nested_and_top_level_skills(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    top = skills / "top-skill"
    nested = skills / "custom" / "nested-skill"
    nested_scripts = nested / "scripts"
    _write_skill(top, name="top-skill", description="top")
    _write_skill(nested, name="nested-skill", description="nested")
    nested_scripts.mkdir(parents=True, exist_ok=True)
    (nested_scripts / "helper.py").write_text("print(1)\n", encoding="utf-8")
    # Group folder without SKILL.md must not become a skill.
    (skills / "custom").mkdir(parents=True, exist_ok=True)

    discovered = discover_workspace_skill_dirs(skills)

    assert set(discovered) == {"top-skill", "nested-skill"}
    assert discovered["top-skill"] == top
    assert discovered["nested-skill"] == nested
    assert resolve_workspace_skill_dir(skills, "nested-skill") == nested
    assert resolve_workspace_skill_dir(skills, "missing") is None


def test_shallower_skill_wins_on_name_collision(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    shallow = skills / "dup"
    deep = skills / "group" / "dup"
    _write_skill(shallow, name="dup", description="shallow")
    _write_skill(deep, name="dup", description="deep")

    discovered = discover_workspace_skill_dirs(skills)

    assert set(discovered) == {"dup"}
    assert discovered["dup"] == shallow


def test_reconcile_and_enable_nested_workspace_skill(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    nested = workspace / "skills" / "custom" / "my-custom"
    _write_skill(nested, name="my-custom", description="custom nested skill")

    manifest = reconcile_workspace_manifest(workspace)
    assert "my-custom" in manifest["skills"]
    assert manifest["skills"]["my-custom"]["enabled"] is False

    service = SkillService(workspace)
    result = service.enable_skill("my-custom")
    assert result["success"] is True
    assert resolve_effective_skills(workspace, "console") == ["my-custom"]

    listed = {skill.name for skill in service.list_all_skills()}
    assert "my-custom" in listed

    available = {skill.name for skill in service.list_available_skills()}
    assert available == {"my-custom"}

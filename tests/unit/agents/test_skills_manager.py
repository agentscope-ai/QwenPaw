# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types


def _install_frontmatter_stub() -> None:
    if "frontmatter" in sys.modules:
        return

    def loads(content: str):
        data: dict[str, str] = {}
        lines = content.splitlines()
        if len(lines) >= 3 and lines[0].strip() == "---":
            for line in lines[1:]:
                if line.strip() == "---":
                    break
                key, _, value = line.partition(":")
                if key and _:
                    data[key.strip()] = value.strip()
        return data

    sys.modules["frontmatter"] = types.SimpleNamespace(loads=loads)


def _load_skills_manager_module():
    _install_frontmatter_stub()
    return importlib.import_module("copaw.agents.skills_manager")


SKILL_TEMPLATE = """---
name: {name}
description: {description}
---

# {name}
"""


def _write_skill(
    root: Path,
    name: str,
    description: str,
    *,
    script_body: str = "print(1)\n",
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(name=name, description=description),
        encoding="utf-8",
    )
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "main.py").write_text(script_body, encoding="utf-8")
    return skill_dir


def _patch_skill_dirs(
    monkeypatch,
    skills_manager_module,
    *,
    builtin_dir: Path,
    customized_dir: Path,
    active_dir: Path,
) -> None:
    monkeypatch.setattr(
        skills_manager_module,
        "get_builtin_skills_dir",
        lambda: builtin_dir,
    )
    monkeypatch.setattr(
        skills_manager_module,
        "get_customized_skills_dir",
        lambda: customized_dir,
    )
    monkeypatch.setattr(
        skills_manager_module,
        "get_active_skills_dir",
        lambda: active_dir,
    )


def test_sync_from_active_to_customized_ignores_runtime_artifacts(
    monkeypatch,
    tmp_path,
) -> None:
    skills_manager_module = _load_skills_manager_module()
    builtin_dir = tmp_path / "builtin"
    customized_dir = tmp_path / "customized"
    active_dir = tmp_path / "active"
    builtin_skill = _write_skill(builtin_dir, "calendar", "builtin calendar")
    active_skill = _write_skill(active_dir, "calendar", "builtin calendar")

    pycache_dir = active_skill / "__pycache__"
    pycache_dir.mkdir(parents=True)
    (pycache_dir / "main.cpython-312.pyc").write_bytes(b"compiled")
    (active_skill / ".DS_Store").write_text("finder", encoding="utf-8")

    _patch_skill_dirs(
        monkeypatch,
        skills_manager_module,
        builtin_dir=builtin_dir,
        customized_dir=customized_dir,
        active_dir=active_dir,
    )

    (
        synced,
        skipped,
    ) = skills_manager_module.sync_skills_from_active_to_customized()

    assert synced == 0
    assert skipped == 1
    assert not (customized_dir / builtin_skill.name).exists()


def test_sync_from_active_to_customized_keeps_real_builtin_edits(
    monkeypatch,
    tmp_path,
) -> None:
    skills_manager_module = _load_skills_manager_module()
    builtin_dir = tmp_path / "builtin"
    customized_dir = tmp_path / "customized"
    active_dir = tmp_path / "active"
    _write_skill(builtin_dir, "calendar", "builtin calendar")
    active_skill = _write_skill(
        active_dir,
        "calendar",
        "builtin calendar",
        script_body="print(2)\n",
    )

    _patch_skill_dirs(
        monkeypatch,
        skills_manager_module,
        builtin_dir=builtin_dir,
        customized_dir=customized_dir,
        active_dir=active_dir,
    )

    (
        synced,
        skipped,
    ) = skills_manager_module.sync_skills_from_active_to_customized()

    assert synced == 1
    assert skipped == 0
    copied_skill = customized_dir / active_skill.name
    assert copied_skill.exists()
    assert (copied_skill / "scripts" / "main.py").read_text(
        encoding="utf-8",
    ) == "print(2)\n"


def test_list_all_skills_prefers_customized_over_builtin_duplicates(
    monkeypatch,
    tmp_path,
) -> None:
    skills_manager_module = _load_skills_manager_module()
    builtin_dir = tmp_path / "builtin"
    customized_dir = tmp_path / "customized"
    active_dir = tmp_path / "active"
    _write_skill(builtin_dir, "calendar", "builtin calendar")
    _write_skill(builtin_dir, "mail", "builtin mail")
    _write_skill(customized_dir, "calendar", "customized calendar")
    _write_skill(customized_dir, "notes", "customized notes")

    _patch_skill_dirs(
        monkeypatch,
        skills_manager_module,
        builtin_dir=builtin_dir,
        customized_dir=customized_dir,
        active_dir=active_dir,
    )

    skills = skills_manager_module.SkillService.list_all_skills()

    assert [skill.name for skill in skills] == ["calendar", "mail", "notes"]
    skills_by_name = {skill.name: skill for skill in skills}
    assert skills_by_name["calendar"].source == "customized"
    assert skills_by_name["calendar"].description == "customized calendar"
    assert skills_by_name["mail"].source == "builtin"
    assert skills_by_name["notes"].source == "customized"

# -*- coding: utf-8 -*-
"""Nested (categorised) skill layout support.

Skills may live at ``<root>/<category>/<skill>/SKILL.md``. The skill identity
stays the leaf directory name (Hermes parity); the manifest records a
``rel_path`` so resolution is exact.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from qwenpaw.agents.skill_system.registry import (
    reconcile_workspace_manifest,
    resolve_effective_skills,
    resolve_workspace_skill_dir,
)
from qwenpaw.agents.skill_system.store import (
    iter_skill_dirs,
    rel_path_of,
    resolve_skill_dir,
)
from qwenpaw.agents.skill_system.workspace_service import SkillService


def _mk_skill(root: Path, rel: str, name: str, extra=()) -> Path:
    directory = root / rel
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill {name}\n---\n\nbody\n",
        encoding="utf-8",
    )
    for entry in extra:
        (directory / entry).mkdir(parents=True, exist_ok=True)
    return directory


def test_iter_skill_dirs_finds_nested(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _mk_skill(skills, "cat-a/skill-1", "skill-1")
    _mk_skill(skills, "cat-a/cat-b/skill-2", "skill-2")
    _mk_skill(skills, "flat-skill", "flat-skill")

    names = sorted(p.name for p in iter_skill_dirs(skills))
    assert names == ["flat-skill", "skill-1", "skill-2"]
    assert (
        rel_path_of(skills, skills / "cat-a/cat-b/skill-2")
        == "cat-a/cat-b/skill-2"
    )


def test_support_dirs_are_pruned(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _mk_skill(
        skills,
        "cat/skill-1",
        "skill-1",
        extra=["scripts", "references"],
    )
    _mk_skill(skills / "cat/skill-1/scripts", "nested", "nested")

    names = [p.name for p in iter_skill_dirs(skills)]
    assert "skill-1" in names
    assert "nested" not in names


def test_reconcile_records_rel_path_and_resolves(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _mk_skill(skills, "cat-a/skill-1", "skill-1")
    _mk_skill(skills, "cat-a/cat-b/skill-2", "skill-2")

    manifest = reconcile_workspace_manifest(tmp_path)
    entry = manifest["skills"]["skill-2"]
    assert entry["rel_path"] == "cat-a/cat-b/skill-2"
    assert entry["enabled"] is False

    for name in ("skill-1", "skill-2"):
        manifest["skills"][name]["enabled"] = True
    (tmp_path / "skill.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    assert set(resolve_effective_skills(tmp_path, "qq")) >= {
        "skill-1",
        "skill-2",
    }
    resolved = resolve_workspace_skill_dir(tmp_path, "skill-2")
    assert resolved is not None
    assert resolved.name == "skill-2"


def test_same_leaf_name_collides_first_wins(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _mk_skill(skills, "a/dup", "dup")
    _mk_skill(skills, "b/dup", "dup")

    resolved = resolve_skill_dir(skills, "dup")
    assert resolved is not None
    assert resolved.parent.name == "a"


def test_zip_import_preserves_nesting(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "cat-x/z-skill/SKILL.md",
            "---\nname: z-skill\ndescription: zz\n---\nbody\n",
        )
        archive.writestr("cat-x/z-skill/references/r.md", "ref\n")

    result = SkillService(tmp_path).import_from_zip(buffer.getvalue())
    assert result["imported"] == ["z-skill"]
    assert (tmp_path / "skills" / "cat-x" / "z-skill" / "SKILL.md").exists()


def test_install_skill_directory_honours_rel_path(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source = _mk_skill(source_root, "n/sk", "sk")

    result = SkillService(tmp_path).install_skill_directory(
        source,
        rel_path="n/sk",
        enable=True,
    )
    assert result["success"] is True
    assert (tmp_path / "skills" / "n" / "sk" / "SKILL.md").exists()


def test_scan_excluded_dirs(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _mk_skill(skills, ".archive/old", "old")
    _mk_skill(skills, "node_modules/nm", "nm")
    _mk_skill(skills, "good", "good")

    assert [p.name for p in iter_skill_dirs(skills)] == ["good"]

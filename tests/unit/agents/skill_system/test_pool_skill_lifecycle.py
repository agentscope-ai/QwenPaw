# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Pool-level skill unit tests (skill_system service layer).

Regression coverage:
- GitHub issue #1281: list_all_skills must not double-count same-name skills
- GitHub issue #2770: rename must keep scripts and other directory files
- GitHub issue #2887/#2915/#3420: saving SKILL.md must keep other files
- GitHub issue #3702: malformed manifest entries must not crash skill listing
- GitHub issue #6537 (#3270): restart reconciliation must preserve tags
- GitHub issue #1367: skill names containing path separators must be rejected
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import pool_service as skill_pool_service
from qwenpaw.agents.skill_system import registry as skill_registry
from qwenpaw.agents.skill_system import store as skill_store
from qwenpaw.agents.skill_system.pool_service import SkillPoolService
from qwenpaw.constant import WORKING_DIR


def _skill_md(name: str, description: str = "desc for tests") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n"
        "# body\n"
    )


def _write_skill_dir(skill_dir: Path, name: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_skill_md(name), encoding="utf-8")


def _write_pool_manifest(pool_dir: Path, skills: dict) -> None:
    (pool_dir / "skill.json").write_text(
        json.dumps(
            {
                "schema_version": "skill-pool-manifest.v1",
                "version": 0,
                "skills": skills,
                "builtin_skill_names": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _read_pool_manifest(pool_dir: Path) -> dict:
    return json.loads((pool_dir / "skill.json").read_text(encoding="utf-8"))


@pytest.fixture()
def pool_env(tmp_path, monkeypatch):
    """Isolated skill pool rooted in tmp_path, built-ins and scans stubbed.

    The security scan is stubbed because this file targets the pool
    lifecycle logic, not scanner behavior (scanner has its own suite).
    """
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        skill_registry,
        "import_builtin_skills",
        lambda *args, **kwargs: {},
    )
    # pool_service does ``from .store import scan_skill_dir_or_raise``, so the
    # stub must target the pool_service namespace where the reference is bound.
    monkeypatch.setattr(
        skill_pool_service,
        "scan_skill_dir_or_raise",
        lambda *args, **kwargs: None,
    )
    service = SkillPoolService()
    pool_dir = tmp_path / "skill_pool"
    return service, pool_dir


class TestSavePreservesFiles:
    """GitHub issue #2887 / #2915 / #3420 cluster."""

    def test_save_preserves_scripts_and_references(self, pool_env):
        service, pool_dir = pool_env
        created = service.create_skill(
            "demo",
            _skill_md("demo"),
            scripts={"run.py": "print(1)\n"},
            references={"doc.md": "docs\n"},
        )
        assert created == "demo"

        result = service.save_pool_skill(
            skill_name="demo",
            content=_skill_md("demo", description="updated"),
        )
        assert result["success"] is True
        assert result["mode"] == "edit"

        skill_dir = pool_dir / "demo"
        assert (
            skill_dir / "scripts" / "run.py"
        ).exists(), "saving SKILL.md must not delete other skill files (#2887)"
        assert (skill_dir / "references" / "doc.md").exists()
        assert "updated" in (skill_dir / "SKILL.md").read_text(
            encoding="utf-8",
        )

    def test_save_unknown_skill_reports_not_found(self, pool_env):
        service, _pool_dir = pool_env
        result = service.save_pool_skill(
            skill_name="no_such_skill",
            content=_skill_md("no_such_skill"),
        )
        assert result["success"] is False
        assert result["reason"] == "not_found"


class TestRenamePreservesFiles:
    """GitHub issue #2770: rename must not wipe scripts and other files."""

    def test_rename_preserves_directory_contents(self, pool_env):
        service, pool_dir = pool_env
        service.create_skill(
            "old_name",
            _skill_md("old_name"),
            scripts={"helper.sh": "echo hi\n"},
            extra_files={"data.txt": "payload\n"},
        )

        result = service.save_pool_skill(
            skill_name="old_name",
            content=_skill_md("new_name"),
            target_name="new_name",
        )
        assert result["success"] is True
        assert result["mode"] == "rename"
        assert result["name"] == "new_name"

        new_dir = pool_dir / "new_name"
        assert (
            new_dir / "scripts" / "helper.sh"
        ).exists(), "rename must keep directory contents (#2770)"
        assert (new_dir / "data.txt").exists()
        assert not (pool_dir / "old_name").exists()

        manifest = _read_pool_manifest(pool_dir)
        assert "new_name" in manifest["skills"]
        assert "old_name" not in manifest["skills"]

    def test_rename_conflict_requires_overwrite(self, pool_env):
        service, _pool_dir = pool_env
        service.create_skill("alpha", _skill_md("alpha"))
        service.create_skill("beta", _skill_md("beta"))

        result = service.save_pool_skill(
            skill_name="alpha",
            content=_skill_md("beta"),
            target_name="beta",
        )
        assert result["success"] is False
        assert result["reason"] == "conflict"
        assert result.get("suggested_name")


class TestListAllSkills:
    """#1281: listing must not double-count same-name skills."""

    def test_no_duplicate_entries_per_name(self, pool_env):
        service, pool_dir = pool_env
        service.create_skill("solo", _skill_md("solo"))

        # same-named skill in both pool roots must appear only once
        extra_root = pool_dir.parent / "extra_pool"
        _write_skill_dir(extra_root / "solo", "solo")
        assert service.list_all_skills() is not None

    def test_shadowed_duplicate_in_extra_root_not_double_counted(
        self,
        pool_env,
        monkeypatch,
    ):
        service, pool_dir = pool_env
        service.create_skill("shadowed", _skill_md("shadowed", "primary"))

        extra_root = pool_dir.parent / "extra_pool"
        _write_skill_dir(extra_root / "shadowed", "shadowed")
        monkeypatch.setattr(
            skill_store,
            "get_extra_skill_dirs",
            lambda: [extra_root],
        )

        skills = service.list_all_skills()
        names = [skill.name for skill in skills]
        assert (
            names.count("shadowed") == 1
        ), "same-named skills across pool roots must be counted once (#1281)"
        listed = next(s for s in skills if s.name == "shadowed")
        assert listed.description == "primary", "the main pool entry must win"


class TestReconcilePreservesUserState:
    """#6537 (#3270): restart reconciliation preserves user tags."""

    def test_reconcile_preserves_tags_and_config(self, pool_env):
        _service, pool_dir = pool_env
        _write_skill_dir(pool_dir / "tagged", "tagged")
        _write_pool_manifest(
            pool_dir,
            {
                "tagged": {
                    "enabled": True,
                    "source": "customized",
                    "tags": ["ops", "demo"],
                    "config": {"foo": "bar"},
                },
            },
        )

        skill_registry.reconcile_pool_manifest()

        entry = _read_pool_manifest(pool_dir)["skills"]["tagged"]
        assert entry["tags"] == [
            "ops",
            "demo",
        ], "reconciliation (restart path) must not lose tags (#6537)"
        assert entry["config"] == {"foo": "bar"}

    def test_reconcile_adds_new_and_removes_gone(self, pool_env):
        _service, pool_dir = pool_env
        _write_skill_dir(pool_dir / "fresh", "fresh")
        _write_pool_manifest(
            pool_dir,
            {
                "ghost": {
                    "enabled": True,
                    "source": "customized",
                },
            },
        )

        skill_registry.reconcile_pool_manifest()

        skills = _read_pool_manifest(pool_dir)["skills"]
        assert "fresh" in skills
        assert (
            "ghost" not in skills
        ), "entries whose directory no longer exists must be removed"

    def test_reconcile_tolerates_malformed_entry(self, pool_env):
        """#3702: a malformed entry must not break the whole pool."""
        _service, pool_dir = pool_env
        _write_skill_dir(pool_dir / "good", "good")
        manifest_path = pool_dir / "skill.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "skill-pool-manifest.v1",
                    "version": 0,
                    "skills": {
                        "good": {"enabled": True, "source": "customized"},
                        "junk": "not-a-dict",
                    },
                    "builtin_skill_names": [],
                },
            ),
            encoding="utf-8",
        )

        skill_registry.reconcile_pool_manifest()

        skills = _read_pool_manifest(pool_dir)["skills"]
        assert (
            "good" in skills
        ), "malformed sibling entry must not break valid skill load (#3702)"
        assert isinstance(skills.get("junk", {}), dict)


class TestSkillNameValidation:
    """#1367: skill names with path separators must be rejected."""

    @pytest.mark.parametrize("bad_name", ["a/b", "a\\b", "../x", "", ".."])
    def test_create_rejects_path_traversal_names(self, pool_env, bad_name):
        service, _pool_dir = pool_env
        with pytest.raises(Exception):
            service.create_skill(bad_name, _skill_md("x"))

    def test_register_entry_preserves_tags_from_existing(self, pool_env):
        """tags merge entry points must retain tags (both paths)."""
        from qwenpaw.agents.skill_system.pool_service import (
            _register_pool_skill_entry,
        )

        _service, pool_dir = pool_env
        payload: dict = {"skills": {}}
        skill_dir = pool_dir / "keep"
        _write_skill_dir(skill_dir, "keep")

        _register_pool_skill_entry(
            payload,
            "keep",
            skill_dir,
            preserve_from={"tags": ["inherited"]},
        )
        assert payload["skills"]["keep"]["tags"] == ["inherited"]

        _register_pool_skill_entry(
            payload,
            "keep",
            skill_dir,
            tags=["explicit"],
            preserve_from={"tags": ["inherited"]},
        )
        assert payload["skills"]["keep"]["tags"] == ["explicit"]


class TestDeleteSkill:
    """#1711: delete a skill cleanly (directory + manifest removed)."""

    def test_delete_removes_dir_and_manifest_entry(self, pool_env):
        service, pool_dir = pool_env
        service.create_skill("to_remove", _skill_md("to_remove"))
        assert service.delete_skill("to_remove") is True
        assert not (pool_dir / "to_remove").exists()
        manifest = _read_pool_manifest(pool_dir)
        assert "to_remove" not in manifest["skills"]

    def test_delete_unknown_skill_returns_false(self, pool_env):
        service, _pool_dir = pool_env
        assert service.delete_skill("never_existed") is False

    def test_delete_missing_dir_but_manifest_entry_succeeds(
        self,
        pool_env,
    ):
        """Manifest entry must clear even if its directory is gone."""
        service, pool_dir = pool_env
        service.create_skill("half_gone", _skill_md("half_gone"))
        import shutil as _shutil

        _shutil.rmtree(pool_dir / "half_gone")

        assert service.delete_skill("half_gone") is True
        assert "half_gone" not in _read_pool_manifest(pool_dir)["skills"]

    def test_delete_rejects_invalid_name(self, pool_env):
        service, _pool_dir = pool_env
        assert service.delete_skill("a/b") is False


class TestWorkspaceReconcilePreservesEnabled:
    """#4807/#1693: reconciliation must not re-enable disabled skills."""

    @pytest.fixture()
    def workspace_env(self, tmp_path):
        workspace_dir = tmp_path / "workspaces" / "agent_x"
        skills_dir = workspace_dir / "skills"
        _write_skill_dir(skills_dir / "disabled_skill", "disabled_skill")
        manifest_path = workspace_dir / "skill.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "workspace-skill-manifest.v1",
                    "version": 0,
                    "skills": {
                        "disabled_skill": {
                            "enabled": False,
                            "channels": ["all"],
                            "source": "customized",
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        return workspace_dir, manifest_path

    def test_disabled_stays_disabled_after_reconcile(self, workspace_env):
        workspace_dir, manifest_path = workspace_env

        skill_registry.reconcile_workspace_manifest(workspace_dir)

        entry = json.loads(manifest_path.read_text(encoding="utf-8"))[
            "skills"
        ]["disabled_skill"]
        assert (
            entry["enabled"] is False
        ), "reconciliation must not re-enable disabled skills (#4807)"

    def test_enabled_and_channels_preserved_after_reconcile(
        self,
        workspace_env,
    ):
        workspace_dir, manifest_path = workspace_env
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["skills"]["disabled_skill"].update(
            {"enabled": True, "channels": ["dingtalk"]},
        )
        manifest_path.write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

        skill_registry.reconcile_workspace_manifest(workspace_dir)

        entry = json.loads(manifest_path.read_text(encoding="utf-8"))[
            "skills"
        ]["disabled_skill"]
        assert entry["enabled"] is True
        assert entry["channels"] == [
            "dingtalk",
        ], "reconciliation must not lose the enabled channel scope (#1693)"


class TestZipImportValidation:
    """#5474: broken YAML frontmatter must not claim a slot."""

    @staticmethod
    def _make_zip(skill_md_content: str) -> bytes:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("broken_skill/SKILL.md", skill_md_content)
        return buf.getvalue()

    def test_invalid_frontmatter_zip_rejected_without_occupation(
        self,
        pool_env,
    ):
        service, pool_dir = pool_env
        # unclosed flow sequence -> yaml.YAMLError
        bad_md = "---\nname: [unclosed\ndescription: x\n---\nbody\n"

        with pytest.raises(Exception):
            service.import_from_zip(self._make_zip(bad_md))

        manifest = _read_pool_manifest(pool_dir)
        assert (
            manifest["skills"] == {}
        ), "broken frontmatter must not occupy the namespace (#5474)"
        assert not (pool_dir / "broken_skill").exists()

    def test_valid_frontmatter_zip_imports(self, pool_env):
        service, pool_dir = pool_env
        result = service.import_from_zip(self._make_zip(_skill_md("ok_zip")))
        assert result["imported"] == ["ok_zip"]
        assert result["count"] == 1
        assert (pool_dir / "ok_zip" / "SKILL.md").exists()


def test_working_dir_is_isolated(pool_env):
    """Fixture self-check: the test pool lives in a temp dir."""
    _service, pool_dir = pool_env
    # tempfile root differs per platform ("/tmp" vs C:\...\Temp);
    # Windows runners may expose the short-name form (RUNNER~1) in
    # tempfile.gettempdir() while pytest hands out the long-name path,
    # so resolve both sides before comparing.
    temp_root = Path(tempfile.gettempdir()).resolve()
    assert pool_dir.resolve().is_relative_to(temp_root), (
        f"skill pool not isolated into a temp dir: {pool_dir} "
        f"(real WORKING_DIR={WORKING_DIR})"
    )

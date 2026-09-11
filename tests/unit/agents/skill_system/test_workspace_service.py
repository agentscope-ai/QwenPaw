# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for skill_system/workspace_service.py (SkillService).

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the workspace-scoped
skill lifecycle (create/save/enable/channels/tags/delete), which
previously sat at ~9% coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import workspace_service as ws_module
from qwenpaw.agents.skill_system.workspace_service import SkillService


def _skill_md(name: str, description: str = "desc for tests") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n# body\n"


@pytest.fixture()
def ws_env(tmp_path, monkeypatch):
    """Isolated workspace with scanner stubbed (pool fixture pattern)."""
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        ws_module,
        "scan_skill_dir_or_raise",
        lambda *args, **kwargs: None,
    )
    workspace_dir = tmp_path / "workspaces" / "agent_x"
    service = SkillService(workspace_dir)
    return service, workspace_dir


def _read_manifest(workspace_dir: Path) -> dict:
    return json.loads(
        (workspace_dir / "skill.json").read_text(encoding="utf-8"),
    )


class TestCreateSkill:
    def test_creates_files_and_manifest_entry(self, ws_env):
        service, workspace_dir = ws_env
        created = service.create_skill(
            "demo",
            _skill_md("demo"),
            scripts={"run.py": "print(1)\n"},
        )
        assert created == "demo"
        assert (workspace_dir / "skills" / "demo" / "SKILL.md").exists()
        assert (
            workspace_dir / "skills" / "demo" / "scripts" / "run.py"
        ).exists()
        entry = _read_manifest(workspace_dir)["skills"]["demo"]
        assert entry["enabled"] is False  # create defaults to disabled

    def test_create_enable_flag(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill("demo", _skill_md("demo"), enable=True)
        entry = _read_manifest(workspace_dir)["skills"]["demo"]
        assert entry["enabled"] is True

    def test_duplicate_create_returns_none(self, ws_env):
        service, _ws = ws_env
        assert service.create_skill("demo", _skill_md("demo")) == "demo"
        assert service.create_skill("demo", _skill_md("demo")) is None

    def test_bad_name_raises(self, ws_env):
        service, _ws = ws_env
        from qwenpaw.exceptions import SkillsError

        with pytest.raises(SkillsError):
            service.create_skill("bad/name", _skill_md("x"))

    def test_invalid_frontmatter_raises(self, ws_env):
        service, _ws = ws_env
        from qwenpaw.exceptions import SkillsError

        with pytest.raises(SkillsError):
            service.create_skill("demo", "---\nname: [unclosed\n---\n")


class TestListSkills:
    def test_list_all_skills(self, ws_env):
        service, _ws = ws_env
        service.create_skill("a", _skill_md("a"))
        service.create_skill("b", _skill_md("b"))
        names = [s.name for s in service.list_all_skills()]
        assert names == ["a", "b"]

    def test_list_all_skips_manifest_only(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill("a", _skill_md("a"))
        # entry in manifest without a directory
        manifest_path = workspace_dir / "skill.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["skills"]["ghost"] = {"enabled": True}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        names = [s.name for s in service.list_all_skills()]
        assert names == ["a"]


class TestSaveSkill:
    def test_edit_in_place_preserves_scripts(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill(
            "demo",
            _skill_md("demo"),
            scripts={"run.py": "print(1)\n"},
        )
        result = service.save_skill(
            skill_name="demo",
            content=_skill_md("demo", "updated"),
        )
        assert result["success"] is True
        assert (
            workspace_dir / "skills" / "demo" / "scripts" / "run.py"
        ).exists()
        assert "updated" in (
            workspace_dir / "skills" / "demo" / "SKILL.md"
        ).read_text(encoding="utf-8")

    def test_save_unknown_skill_not_found(self, ws_env):
        service, _ws = ws_env
        result = service.save_skill(skill_name="ghost", content=_skill_md("g"))
        assert result == {"success": False, "reason": "not_found"}

    def test_save_bad_name_not_found(self, ws_env):
        service, _ws = ws_env
        result = service.save_skill(
            skill_name="bad/name",
            content=_skill_md("x"),
        )
        assert result == {"success": False, "reason": "not_found"}

    def test_rename_conflict_without_overwrite(self, ws_env):
        service, _ws = ws_env
        service.create_skill("a", _skill_md("a"))
        service.create_skill("b", _skill_md("b"))
        result = service.save_skill(
            skill_name="a",
            content=_skill_md("b"),
            target_name="b",
        )
        assert result["success"] is False
        assert result["reason"] == "conflict"
        assert result["suggested_name"]

    def test_rename_with_overwrite(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill("a", _skill_md("a"))
        service.create_skill("b", _skill_md("b"))
        result = service.save_skill(
            skill_name="a",
            content=_skill_md("b", "merged"),
            target_name="b",
            overwrite=True,
        )
        assert result["success"] is True
        assert not (workspace_dir / "skills" / "a").exists()
        manifest = _read_manifest(workspace_dir)["skills"]
        assert "a" not in manifest
        assert "b" in manifest

    def test_rename_new_name(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill("a", _skill_md("a"))
        result = service.save_skill(
            skill_name="a",
            content=_skill_md("c"),
            target_name="c",
        )
        assert result["success"] is True
        assert (workspace_dir / "skills" / "c" / "SKILL.md").exists()
        manifest = _read_manifest(workspace_dir)["skills"]
        assert "a" not in manifest
        assert "c" in manifest


class TestEnableDisable:
    def test_enable_and_disable(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill("demo", _skill_md("demo"))

        enabled = service.enable_skill("demo")
        assert enabled["success"] is True
        entry = _read_manifest(workspace_dir)["skills"]["demo"]
        assert entry["enabled"] is True

        disabled = service.disable_skill("demo")
        assert disabled["success"] is True
        entry = _read_manifest(workspace_dir)["skills"]["demo"]
        assert entry["enabled"] is False

    def test_enable_unknown_returns_failure(self, ws_env):
        service, _ws = ws_env
        result = service.enable_skill("ghost")
        assert result["success"] is False

    def test_disable_unknown_reports_no_workspaces(self, ws_env):
        service, _ws = ws_env
        result = service.disable_skill("ghost")
        assert result["success"] is False


class TestChannelsAndTags:
    def test_set_channels(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill("demo", _skill_md("demo"))
        assert service.set_skill_channels("demo", ["discord"]) is True
        entry = _read_manifest(workspace_dir)["skills"]["demo"]
        assert entry["channels"] == ["discord"]

    def test_set_channels_unknown_false(self, ws_env):
        service, _ws = ws_env
        assert service.set_skill_channels("ghost", ["discord"]) is False

    def test_set_channels_bad_name_false(self, ws_env):
        service, _ws = ws_env
        assert service.set_skill_channels("bad/name", ["discord"]) is False

    def test_set_tags(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill("demo", _skill_md("demo"))
        assert service.set_skill_tags("demo", ["t1", "t2"]) is True
        entry = _read_manifest(workspace_dir)["skills"]["demo"]
        assert entry["tags"] == ["t1", "t2"]

    def test_set_tags_unknown_false(self, ws_env):
        service, _ws = ws_env
        assert service.set_skill_tags("ghost", ["t"]) is False


class TestDeleteSkill:
    def test_delete_removes_dir_and_entry(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill("demo", _skill_md("demo"))
        assert service.delete_skill("demo") is True
        assert not (workspace_dir / "skills" / "demo").exists()
        assert "demo" not in _read_manifest(workspace_dir)["skills"]

    def test_delete_missing_skill_returns_false(self, ws_env):
        service, _ws = ws_env
        assert service.delete_skill("ghost") is False

    def test_delete_enabled_skill_refused(self, ws_env):
        service, workspace_dir = ws_env
        service.create_skill("demo", _skill_md("demo"), enable=True)
        assert service.delete_skill("demo") is False
        assert (workspace_dir / "skills" / "demo").exists()

    def test_delete_bad_name_false(self, ws_env):
        service, _ws = ws_env
        assert service.delete_skill("bad/name") is False


class TestZipImport:
    @staticmethod
    def _make_zip(name: str = "zipped", body: str = "body text") -> bytes:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(f"{name}/SKILL.md", _skill_md(name, body))
        return buf.getvalue()

    def test_import_valid_zip(self, ws_env):
        service, workspace_dir = ws_env
        result = service.import_from_zip(self._make_zip())
        assert result["imported"] == ["zipped"]
        assert result["count"] == 1
        assert result["conflicts"] == []
        assert (workspace_dir / "skills" / "zipped" / "SKILL.md").exists()

    def test_import_conflict_reports_not_success(self, ws_env):
        service, _ws = ws_env
        service.create_skill("zipped", _skill_md("zipped"))
        result = service.import_from_zip(self._make_zip())
        assert result["imported"] == []
        assert len(result["conflicts"]) == 1

    def test_import_bad_zip_raises(self, ws_env):
        from qwenpaw.exceptions import SkillsError

        service, _ws = ws_env
        with pytest.raises(SkillsError):
            service.import_from_zip(b"not a zip")

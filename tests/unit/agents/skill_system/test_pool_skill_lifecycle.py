# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Pool-level skill unit tests (skill_system service layer).

Regression scope (后端单测缺口补齐第 1 批，A 档)：
- GitHub issue #1281: list_all_skills 不得对同名技能重复计数
- GitHub issue #2770: 重命名技能必须保留目录内脚本等文件
- GitHub issue #2887 / #2915 / #3420: 保存 SKILL.md 不得删除技能目录下其他文件
- GitHub issue #3702: manifest 中畸形条目不得导致列表崩溃
- GitHub issue #6537 (#3270 回归): 重启协调（reconcile）必须保留已有 tags
- GitHub issue #1367: 技能名含路径分隔符必须被拒绝

出处：泰哥 2026-08-23 批复（xiaoyi:a1430f5b2a1640a89057fd9acb572757，
姜子牙转达）后端单测缺口补齐计划第 1 批。
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
    """GitHub issue #2887 / #2915 / #3420 簇。"""

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
        ).exists(), "保存 SKILL.md 不得删除技能目录下的脚本（#2887 簇）"
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
    """GitHub issue #2770：重命名不得清空脚本等文件。"""

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
        ).exists(), "重命名必须保留目录内容（#2770）"
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
    """GitHub issue #1281：列表不得对同名技能重复计数。"""

    def test_no_duplicate_entries_per_name(self, pool_env):
        service, pool_dir = pool_env
        service.create_skill("solo", _skill_md("solo"))

        # 双池根同名技能（主池 + 额外只读根）→ 只能出现一次
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
        assert names.count("shadowed") == 1, "主池与额外根同名技能只能计一次（#1281）"
        listed = next(s for s in skills if s.name == "shadowed")
        assert listed.description == "primary", "主池条目必须胜出"


class TestReconcilePreservesUserState:
    """GitHub issue #6537（#3270 回归）：重启协调保留 tags 等用户状态。"""

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
        assert entry["tags"] == ["ops", "demo"], "协调（重启路径）不得丢失 tags（#6537）"
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
        assert "ghost" not in skills, "目录已不存在的条目必须被移除"

    def test_reconcile_tolerates_malformed_entry(self, pool_env):
        """GitHub issue #3702：畸形条目不得导致整池报错。"""
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
        assert "good" in skills, "畸形兄弟条目不得影响正常技能加载（#3702）"
        assert isinstance(skills.get("junk", {}), dict)


class TestSkillNameValidation:
    """GitHub issue #1367：含路径分隔符的技能名必须被拒绝。"""

    @pytest.mark.parametrize("bad_name", ["a/b", "a\\b", "../x", "", ".."])
    def test_create_rejects_path_traversal_names(self, pool_env, bad_name):
        service, _pool_dir = pool_env
        with pytest.raises(Exception):
            service.create_skill(bad_name, _skill_md("x"))

    def test_register_entry_preserves_tags_from_existing(self, pool_env):
        """tags 合并入口：显式传入与 preserve_from 继承两路都不得丢。"""
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
    """GitHub issue #1711：删除技能必须干净无报错（目录+清单一致清除）。"""

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
        """目录已被手动删掉（#1711 场景）时，清单条目仍应能被清除。"""
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
    """GitHub issue #4807 / #1693：升级/重启协调不得把已禁用技能重置为启用。"""

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
        assert entry["enabled"] is False, "升级/重启协调不得把已禁用技能重置为启用（#4807）"

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
        assert entry["channels"] == ["dingtalk"], "协调不得丢失渠道启用范围（#1693 相关）"


class TestZipImportValidation:
    """GitHub issue #5474：坏 YAML frontmatter 的 ZIP 不得假成功占位。"""

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
        # 未闭合的流式序列 → yaml.YAMLError
        bad_md = "---\nname: [unclosed\ndescription: x\n---\nbody\n"

        with pytest.raises(Exception):
            service.import_from_zip(self._make_zip(bad_md))

        manifest = _read_pool_manifest(pool_dir)
        assert manifest["skills"] == {}, "坏 frontmatter 不得占用命名空间（#5474）"
        assert not (pool_dir / "broken_skill").exists()

    def test_valid_frontmatter_zip_imports(self, pool_env):
        service, pool_dir = pool_env
        result = service.import_from_zip(self._make_zip(_skill_md("ok_zip")))
        assert result["imported"] == ["ok_zip"]
        assert result["count"] == 1
        assert (pool_dir / "ok_zip" / "SKILL.md").exists()


def test_working_dir_is_isolated(pool_env):
    """夹具自检：测试池必须落在临时目录，不得污染真实工作区。"""
    _service, pool_dir = pool_env
    # tempfile root differs per platform ("/tmp" vs C:\...\Temp).
    assert str(pool_dir).startswith(tempfile.gettempdir()), (
        f"技能池未隔离到临时目录: {pool_dir}（真实 WORKING_DIR=" f"{WORKING_DIR}）"
    )

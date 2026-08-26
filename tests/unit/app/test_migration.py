# -*- coding: utf-8 -*-
# pylint: disable=consider-using-from-import,protected-access,redefined-outer-name,unnecessary-lambda,unused-argument,unused-import,unused-variable,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for app/migration.py legacy migration helpers.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: workspace-item migration,
legacy workspace → default agent migration, and legacy skill layout
migration, which previously sat at ~8% coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import qwenpaw.app.migration as migration


@pytest.fixture()
def working_dir(tmp_path, monkeypatch):
    wd = tmp_path / "wd"
    wd.mkdir()
    monkeypatch.setattr(migration, "WORKING_DIR", wd)
    return wd


def _config(profiles=None):
    from qwenpaw.config.config import Config

    cfg = Config()
    if profiles is not None:
        cfg.agents.profiles = profiles
    return cfg


def _ref(agent_id: str, workspace_dir: str):
    from qwenpaw.config.config import AgentProfileRef

    return AgentProfileRef(id=agent_id, workspace_dir=workspace_dir)


# ---------------------------------------------------------------------------
# _migrate_workspace_item
# ---------------------------------------------------------------------------


class TestMigrateWorkspaceItem:
    def test_missing_source_is_skipped(self, tmp_path):
        migrated = []
        migration._migrate_workspace_item(
            tmp_path / "nope",
            tmp_path / "dst",
            "nope",
            migrated,
        )
        assert migrated == []

    def test_existing_target_is_skipped(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.write_text("new")
        dst.write_text("old")
        migrated = []
        migration._migrate_workspace_item(src, dst, "f", migrated)
        assert migrated == []
        assert dst.read_text() == "old"

    def test_file_copied(self, tmp_path):
        src = tmp_path / "src" / "f.json"
        src.parent.mkdir()
        src.write_text("data")
        migrated = []
        migration._migrate_workspace_item(
            src,
            tmp_path / "dst" / "f.json",
            "f.json",
            migrated,
        )
        assert migrated == ["f.json"]
        assert (tmp_path / "dst" / "f.json").read_text() == "data"

    def test_dir_copied(self, tmp_path):
        src = tmp_path / "sessions"
        (src / "sub").mkdir(parents=True)
        (src / "sub" / "s.json").write_text("{}")
        migrated = []
        migration._migrate_workspace_item(
            src,
            tmp_path / "dst" / "sessions",
            "sessions",
            migrated,
        )
        assert migrated == ["sessions"]
        assert (tmp_path / "dst" / "sessions" / "sub" / "s.json").exists()

    def test_copy_error_is_swallowed(self, tmp_path, monkeypatch):
        src = tmp_path / "f.txt"
        src.write_text("x")

        import shutil as _shutil

        def boom(*args, **kwargs):
            raise OSError("denied")

        monkeypatch.setattr(migration.shutil, "copy2", boom)
        migrated = []
        migration._migrate_workspace_item(
            src,
            tmp_path / "dst" / "f.txt",
            "f.txt",
            migrated,
        )
        assert migrated == []


class TestMigrateWorkspaceItemsFromSource:
    def test_migrates_known_items_and_md_files(self, tmp_path):
        src = tmp_path / "root"
        src.mkdir()
        (src / "chats.json").write_text("{}")
        (src / "AGENTS.md").write_text("# agents")
        (src / "unrelated.txt").write_text("x")
        dst = tmp_path / "target"
        dst.mkdir()

        migrated = []
        migration._migrate_workspace_items_from_source(src, dst, migrated)

        assert "chats.json" in migrated
        assert "AGENTS.md" in migrated
        assert "unrelated.txt" not in migrated
        assert (dst / "chats.json").exists()
        assert (dst / "AGENTS.md").exists()

    def test_missing_source_dir_ok(self, tmp_path):
        migrated = []
        migration._migrate_workspace_items_from_source(
            tmp_path / "missing",
            tmp_path / "dst",
            migrated,
        )
        assert migrated == []


# ---------------------------------------------------------------------------
# migrate_legacy_workspace_to_default_agent
# ---------------------------------------------------------------------------


class TestMigrateLegacyWorkspace:
    def test_exception_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            migration,
            "_do_migrate_legacy_workspace",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert migration.migrate_legacy_workspace_to_default_agent() is False

    def test_multi_agent_config_skipped(self, working_dir, monkeypatch):
        cfg = _config(
            {
                "default": _ref(
                    "default",
                    str(working_dir / "ws" / "default"),
                ),
                "other": _ref("other", str(working_dir / "ws" / "other")),
            },
        )
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        assert migration._do_migrate_legacy_workspace() is False

    def test_default_already_migrated_skipped(self, working_dir, monkeypatch):
        ws = working_dir / "workspaces" / "default"
        ws.mkdir(parents=True)
        (ws / "agent.json").write_text("{}")
        cfg = _config({"default": _ref("default", str(ws))})
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        assert migration._do_migrate_legacy_workspace() is False

    def test_load_config_failure_returns_false(self, working_dir, monkeypatch):
        monkeypatch.setattr(
            migration,
            "load_config",
            lambda: (_ for _ in ()).throw(RuntimeError("bad config")),
        )
        assert migration._do_migrate_legacy_workspace() is False

    def test_full_migration_creates_workspace_and_config(
        self,
        working_dir,
        monkeypatch,
    ):
        cfg = _config({})
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        saved = []
        monkeypatch.setattr(
            migration,
            "save_config",
            lambda c: saved.append(c),
        )

        # legacy artifacts at the working-dir root
        (working_dir / "chats.json").write_text('{"version": 1}')
        (working_dir / "AGENTS.md").write_text("# agents")

        assert migration._do_migrate_legacy_workspace() is True

        ws = working_dir / "workspaces" / "default"
        assert (ws / "agent.json").exists()
        agent = json.loads((ws / "agent.json").read_text(encoding="utf-8"))
        assert agent["id"] == "default"
        assert agent["name"] == "Default Agent"
        # legacy items migrated into the new workspace
        assert (ws / "chats.json").exists()
        assert (ws / "AGENTS.md").exists()
        # root config rebuilt around the default agent
        assert len(saved) == 1
        new_cfg = saved[0]
        assert new_cfg.agents.active_agent == "default"
        assert "default" in new_cfg.agents.profiles


# ---------------------------------------------------------------------------
# migrate_legacy_skills_to_skill_pool
# ---------------------------------------------------------------------------


class TestMigrateLegacySkills:
    def test_exception_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            migration,
            "_do_migrate_legacy_skills",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert migration.migrate_legacy_skills_to_skill_pool() is False

    def test_pool_manifest_exists_skips(self, working_dir, monkeypatch):
        from qwenpaw.agents.skill_system import store as skill_store

        monkeypatch.setattr(
            skill_store,
            "get_pool_skill_manifest_path",
            lambda: working_dir / "skill_pool" / "skill.json",
        )
        pool_dir = working_dir / "skill_pool"
        pool_dir.mkdir(parents=True)
        (pool_dir / "skill.json").write_text("{}")
        assert migration._do_migrate_legacy_skills() is False

    def test_config_failure_returns_false(self, working_dir, monkeypatch):
        from qwenpaw.agents.skill_system import store as skill_store

        monkeypatch.setattr(
            skill_store,
            "get_pool_skill_manifest_path",
            lambda: working_dir / "skill_pool" / "skill.json",
        )
        monkeypatch.setattr(
            migration,
            "load_config",
            lambda: (_ for _ in ()).throw(RuntimeError("bad")),
        )
        # ensure_skill_pool_initialized must not create the manifest here
        monkeypatch.setattr(
            "qwenpaw.agents.skill_system.ensure_skill_pool_initialized",
            lambda: False,
        )
        assert migration._do_migrate_legacy_skills() is False

    def test_pool_init_failure_returns_false(self, working_dir, monkeypatch):
        from qwenpaw.agents.skill_system import store as skill_store

        monkeypatch.setattr(
            skill_store,
            "get_pool_skill_manifest_path",
            lambda: working_dir / "skill_pool" / "skill.json",
        )
        monkeypatch.setattr(
            "qwenpaw.agents.skill_system.ensure_skill_pool_initialized",
            lambda: (_ for _ in ()).throw(RuntimeError("init failed")),
        )
        assert migration._do_migrate_legacy_skills() is False


# ---------------------------------------------------------------------------
# ensure_default_agent_exists
# ---------------------------------------------------------------------------


class TestEnsureDefaultAgent:
    def test_exception_swallowed(self, monkeypatch):
        monkeypatch.setattr(
            migration,
            "_do_ensure_default_agent",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        migration.ensure_default_agent_exists()  # must not raise

    def test_already_exists_noop(self, working_dir, monkeypatch):
        cfg = _config(
            {"default": _ref("default", str(working_dir / "ws" / "default"))},
        )
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        saved = []
        monkeypatch.setattr(
            migration,
            "save_config",
            lambda c: saved.append(c),
        )
        migration._do_ensure_default_agent()
        assert saved == []

    def test_creates_missing_default(self, working_dir, monkeypatch):
        cfg = _config({})
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        saved = []
        monkeypatch.setattr(
            migration,
            "save_config",
            lambda c: saved.append(c),
        )
        agent_configs = []
        monkeypatch.setattr(
            migration,
            "save_agent_config",
            lambda agent_id, agent_config: agent_configs.append(agent_id),
        )
        migration._do_ensure_default_agent()
        assert len(saved) == 1
        assert "default" in saved[0].agents.profiles
        assert saved[0].agents.active_agent == "default"
        assert agent_configs == ["default"]
        assert (working_dir / "workspaces" / "default").is_dir()


# ---------------------------------------------------------------------------
# ensure_qa_agent_exists
# ---------------------------------------------------------------------------


class TestEnsureQaAgent:
    def test_exception_swallowed(self, monkeypatch):
        monkeypatch.setattr(
            migration,
            "_do_ensure_qa_agent",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        migration.ensure_qa_agent_exists()  # must not raise

    def test_existing_qa_agent_noop(self, working_dir, monkeypatch):
        from qwenpaw.constant import BUILTIN_QA_AGENT_ID

        cfg = _config(
            {
                BUILTIN_QA_AGENT_ID: _ref(
                    BUILTIN_QA_AGENT_ID,
                    str(working_dir / "ws" / BUILTIN_QA_AGENT_ID),
                ),
            },
        )
        monkeypatch.setattr(migration, "load_config", lambda: cfg)
        saved = []
        monkeypatch.setattr(
            migration,
            "save_config",
            lambda c: saved.append(c),
        )
        migration._do_ensure_qa_agent()
        assert saved == []


class TestLegacyQaDisable:
    def test_disables_legacy_qa_profile(self):
        from qwenpaw.constant import LEGACY_QA_AGENT_ID

        cfg = _config(
            {LEGACY_QA_AGENT_ID: _ref(LEGACY_QA_AGENT_ID, "/tmp/ws_qa")},
        )
        migration._apply_legacy_qa_disable_for_migration(cfg)
        # the legacy profile should have been removed/disabled
        assert LEGACY_QA_AGENT_ID not in cfg.agents.profiles or (
            getattr(cfg.agents.profiles[LEGACY_QA_AGENT_ID], "enabled", True)
            is False
        )

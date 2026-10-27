# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-variable,use-implicit-booleaness-not-comparison  # noqa: E501
"""Pool workspace-sync unit tests (skill_system service layer).

Coverage-driven backfill (batch 3, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the workspace download /
rename-broadcast / auto-update sync paths in ``pool_service.py``, which
previously sat at ~38% coverage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import pool_service as skill_pool_service
from qwenpaw.agents.skill_system import registry as skill_registry
from qwenpaw.agents.skill_system.pool_service import (
    SkillPoolService,
    _detect_changed_auto_sync_skills,
    run_pool_auto_sync,
)


def _skill_md(name: str, body: str = "# body") -> str:
    return f"---\nname: {name}\ndescription: d\n---\n{body}\n"


def _write_skill_dir(skill_dir: Path, name: str, body: str = "# body") -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        _skill_md(name, body),
        encoding="utf-8",
    )


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


def _read_workspace_manifest(workspace_dir: Path) -> dict:
    return json.loads(
        (workspace_dir / "skill.json").read_text(encoding="utf-8"),
    )


def _seed_workspace_skill(
    workspace_dir: Path,
    name: str,
    entry: dict,
) -> None:
    _write_skill_dir(workspace_dir / "skills" / name, name)
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "schema_version": "workspace-skill-manifest.v1",
                "version": 0,
                "skills": {name: entry},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def pool_env(tmp_path, monkeypatch):
    """Isolated skill pool rooted in tmp_path, built-ins and scans stubbed."""
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        skill_registry,
        "import_builtin_skills",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        skill_pool_service,
        "scan_skill_dir_or_raise",
        lambda *args, **kwargs: None,
    )
    service = SkillPoolService()
    pool_dir = tmp_path / "skill_pool"
    workspace_dir = tmp_path / "workspaces" / "agent_x"
    workspace_dir.mkdir(parents=True)
    return service, pool_dir, workspace_dir


class TestDownloadToWorkspace:
    def test_fresh_download_creates_skill_and_entry(self, pool_env):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo"))
        _write_pool_manifest(
            pool_dir,
            {
                "demo": {
                    "source": "customized",
                    "version_text": "1.0",
                },
            },
        )

        result = service.download_to_workspace(
            "demo",
            workspace_dir,
            overwrite=False,
        )

        assert result["success"] is True
        assert result["name"] == "demo"
        assert result["workspace_id"] == "agent_x"
        assert (workspace_dir / "skills" / "demo" / "SKILL.md").exists()
        entry = _read_workspace_manifest(workspace_dir)["skills"]["demo"]
        assert entry["enabled"] is True
        assert entry["channels"] == ["all"]
        assert entry["source"] == "customized"

    def test_unknown_skill_not_found(self, pool_env):
        service, pool_dir, workspace_dir = pool_env
        _write_pool_manifest(pool_dir, {})
        result = service.download_to_workspace("ghost", workspace_dir)
        assert result == {"success": False, "reason": "not_found"}

    def test_bad_name_not_found(self, pool_env):
        service, pool_dir, workspace_dir = pool_env
        _write_pool_manifest(pool_dir, {})
        result = service.download_to_workspace("bad/name", workspace_dir)
        assert result == {"success": False, "reason": "not_found"}

    def test_customized_conflict_blocks_without_overwrite(self, pool_env):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo"))
        _write_pool_manifest(pool_dir, {"demo": {"source": "customized"}})
        _seed_workspace_skill(
            workspace_dir,
            "demo",
            {"source": "customized", "enabled": False},
        )

        result = service.download_to_workspace(
            "demo",
            workspace_dir,
            overwrite=False,
        )

        assert result["success"] is False
        assert result["reason"] == "conflict"
        assert result["suggested_name"]

    def test_overwrite_preserves_prior_enabled_and_config(self, pool_env):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo"))
        _write_pool_manifest(
            pool_dir,
            {"demo": {"source": "customized", "config": {"pool": True}}},
        )
        _seed_workspace_skill(
            workspace_dir,
            "demo",
            {
                "source": "customized",
                "enabled": False,
                "channels": ["dingtalk"],
                "config": {"keep": 1},
                "tags": ["mine"],
            },
        )

        result = service.download_to_workspace(
            "demo",
            workspace_dir,
            overwrite=True,
        )

        assert result["success"] is True
        entry = _read_workspace_manifest(workspace_dir)["skills"]["demo"]
        assert entry["enabled"] is False
        assert entry["channels"] == ["dingtalk"]
        assert entry["config"] == {"keep": 1}
        assert entry["tags"] == ["mine"]

    def test_builtin_same_version_unchanged_with_language_backfill(
        self,
        pool_env,
    ):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo"))
        _write_pool_manifest(
            pool_dir,
            {
                "demo": {
                    "source": "builtin",
                    "version_text": "1.0",
                    "builtin_language": "zh",
                },
            },
        )
        _seed_workspace_skill(
            workspace_dir,
            "demo",
            {
                "source": "builtin",
                "metadata": {"version_text": "1.0"},
            },
        )

        result = service.download_to_workspace(
            "demo",
            workspace_dir,
            overwrite=False,
        )

        assert result["success"] is True
        assert result["mode"] == "unchanged"
        assert result["backfill_language"] == "zh"
        entry = _read_workspace_manifest(workspace_dir)["skills"]["demo"]
        assert entry["builtin_language"] == "zh"

    def test_builtin_version_mismatch_reports_upgrade(self, pool_env):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo"))
        _write_pool_manifest(
            pool_dir,
            {"demo": {"source": "builtin", "version_text": "2.0"}},
        )
        _seed_workspace_skill(
            workspace_dir,
            "demo",
            {
                "source": "builtin",
                "metadata": {"version_text": "1.0"},
            },
        )

        result = service.download_to_workspace(
            "demo",
            workspace_dir,
            overwrite=False,
        )

        assert result["success"] is False
        assert result["reason"] == "builtin_upgrade"
        assert result["source_version_text"] == "2.0"
        assert result["current_version_text"] == "1.0"

    def test_builtin_language_switch_blocked_when_content_differs(
        self,
        pool_env,
    ):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo", body="pool body"))
        _write_pool_manifest(
            pool_dir,
            {
                "demo": {
                    "source": "builtin",
                    "version_text": "1.0",
                    "builtin_language": "en",
                },
            },
        )
        _seed_workspace_skill(
            workspace_dir,
            "demo",
            {
                "source": "builtin",
                "metadata": {"version_text": "1.0"},
                "builtin_language": "zh",
            },
        )
        # workspace SKILL.md differs from pool → content hashes differ
        (workspace_dir / "skills" / "demo" / "SKILL.md").write_text(
            _skill_md("demo", body="different workspace body"),
            encoding="utf-8",
        )

        result = service.download_to_workspace(
            "demo",
            workspace_dir,
            overwrite=False,
        )

        assert result["success"] is False
        assert result["reason"] == "language_switch"
        assert result["source_language"] == "en"
        assert result["current_language"] == "zh"

    def test_builtin_both_languages_set_and_differ_blocks(
        self,
        pool_env,
    ):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo"))
        _write_pool_manifest(
            pool_dir,
            {
                "demo": {
                    "source": "builtin",
                    "version_text": "1.0",
                    "builtin_language": "en",
                },
            },
        )
        _seed_workspace_skill(
            workspace_dir,
            "demo",
            {
                "source": "builtin",
                "metadata": {"version_text": "1.0"},
                "builtin_language": "zh",
            },
        )

        result = service.download_to_workspace(
            "demo",
            workspace_dir,
            overwrite=False,
        )

        # Both languages recorded and differing → language_switch, no
        # content comparison in this branch.
        assert result["success"] is False
        assert result["reason"] == "language_switch"

    def test_preflight_download_reports_conflict(self, pool_env):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo"))
        _write_pool_manifest(pool_dir, {"demo": {"source": "customized"}})
        _seed_workspace_skill(
            workspace_dir,
            "demo",
            {"source": "customized"},
        )

        result = service.preflight_download_to_workspace(
            "demo",
            workspace_dir,
        )
        assert result["success"] is False
        assert result["reason"] == "conflict"

    def test_preflight_download_not_found(self, pool_env):
        service, pool_dir, workspace_dir = pool_env
        _write_pool_manifest(pool_dir, {})
        result = service.preflight_download_to_workspace(
            "ghost",
            workspace_dir,
        )
        assert result == {"success": False, "reason": "not_found"}


class TestTagsAndAutoUpdate:
    def test_set_pool_skill_tags(self, pool_env):
        service, pool_dir, _ws = pool_env
        service.create_skill("demo", _skill_md("demo"))
        assert service.set_pool_skill_tags("demo", ["a", "b"]) is True
        entry = _read_pool_manifest(pool_dir)["skills"]["demo"]
        assert entry["tags"] == ["a", "b"]

    def test_set_pool_skill_tags_unknown_returns_false(self, pool_env):
        service, pool_dir, _ws = pool_env
        _write_pool_manifest(pool_dir, {})
        assert service.set_pool_skill_tags("ghost", ["a"]) is False

    def test_set_pool_skill_tags_bad_name_returns_false(self, pool_env):
        service, pool_dir, _ws = pool_env
        _write_pool_manifest(pool_dir, {})
        assert service.set_pool_skill_tags("bad/name", None) is False

    def test_set_skill_auto_sync_enable_and_disable(
        self,
        pool_env,
        monkeypatch,
    ):
        service, pool_dir, _ws = pool_env
        monkeypatch.setattr(
            skill_pool_service,
            "list_workspaces",
            lambda: [],
        )
        service.create_skill("demo", _skill_md("demo"))

        enabled = service.set_skill_auto_sync(
            "demo",
            enabled=True,
            targets=["agent_x"],
        )
        # Enabling returns the sync result of the immediate push (no
        # workspaces configured → synced entry with an empty agent list).
        assert enabled == {
            "synced": [{"skill": "demo", "agents": []}],
            "failed": [],
            "checked": 1,
        }
        entry = _read_pool_manifest(pool_dir)["skills"]["demo"]
        sync_config = entry["automation"]["auto_sync"]
        assert sync_config["enabled"] is True
        assert sync_config["targets"] == ["agent_x"]
        # The immediate sync stamps the hash (no targets to push to).
        assert sync_config["synced_hash"]
        # Legacy flat keys are migrated into the automation namespace.
        assert "auto_update" not in entry

        disabled = service.set_skill_auto_sync(
            "demo",
            enabled=False,
            targets=None,
        )
        assert disabled == {"synced": [], "failed": [], "checked": 0}
        entry = _read_pool_manifest(pool_dir)["skills"]["demo"]
        sync_config = entry["automation"]["auto_sync"]
        assert sync_config["enabled"] is False
        assert "targets" not in sync_config

    def test_set_skill_auto_sync_unknown_returns_none(self, pool_env):
        service, pool_dir, _ws = pool_env
        _write_pool_manifest(pool_dir, {})
        assert (
            service.set_skill_auto_sync("ghost", enabled=True, targets=None)
            is None
        )

    def test_set_skill_auto_sync_bad_name_returns_none(self, pool_env):
        service, pool_dir, _ws = pool_env
        _write_pool_manifest(pool_dir, {})
        assert (
            service.set_skill_auto_sync(
                "bad/name",
                enabled=True,
                targets=None,
            )
            is None
        )


class TestAutoUpdateSync:
    def test_detect_changed_skips_disabled(self, pool_env):
        _service, pool_dir, _ws = pool_env
        _write_skill_dir(pool_dir / "on", "on")
        _write_skill_dir(pool_dir / "off", "off")
        entries = {
            "on": {"auto_update": True, "auto_update_synced_hash": ""},
            "off": {"auto_update": False},
            "junk": "not-a-dict",
        }
        changed, checked = _detect_changed_auto_sync_skills(entries, None)
        assert checked == 1
        assert [name for name, _entry, _hash in changed] == ["on"]

    def test_detect_changed_respects_name_filter(self, pool_env):
        _service, pool_dir, _ws = pool_env
        _write_skill_dir(pool_dir / "a", "a")
        _write_skill_dir(pool_dir / "b", "b")
        entries = {
            "a": {"auto_update": True},
            "b": {"auto_update": True},
        }
        changed, checked = _detect_changed_auto_sync_skills(entries, "a")
        assert checked == 1
        assert [name for name, *_ in changed] == ["a"]

    def test_detect_changed_skips_missing_dir(self, pool_env):
        _service, _pool_dir, _ws = pool_env
        entries = {
            "ghost": {"auto_update": True},
        }
        changed, checked = _detect_changed_auto_sync_skills(entries, None)
        assert checked == 1
        assert changed == []

    def test_detect_changed_matches_hash_no_change(self, pool_env):
        _service, pool_dir, _ws = pool_env
        _write_skill_dir(pool_dir / "same", "same")
        skill_md = (pool_dir / "same" / "SKILL.md").read_text(encoding="utf-8")
        current_hash = hashlib.sha256(skill_md.encode("utf-8")).hexdigest()
        entries = {
            "same": {
                "auto_update": True,
                "auto_update_synced_hash": current_hash,
            },
        }
        changed, checked = _detect_changed_auto_sync_skills(entries, None)
        assert checked == 1
        assert changed == []

    def test_run_sync_no_changed_skills(self, pool_env):
        _service, pool_dir, _ws = pool_env
        _write_pool_manifest(pool_dir, {"off": {"auto_update": False}})
        result = run_pool_auto_sync()
        assert result == {"synced": [], "failed": [], "checked": 0}

    def test_run_sync_pushes_to_target_workspaces(self, pool_env, monkeypatch):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo"))
        _write_pool_manifest(
            pool_dir,
            {
                "demo": {
                    "source": "customized",
                    "auto_update": True,
                    "auto_update_targets": ["agent_x"],
                },
            },
        )
        monkeypatch.setattr(
            skill_pool_service,
            "list_workspaces",
            lambda: [
                {
                    "agent_id": "agent_x",
                    "agent_name": "Agent X",
                    "workspace_dir": str(workspace_dir),
                },
                {
                    "agent_id": "agent_y",
                    "agent_name": "Agent Y",
                    "workspace_dir": str(workspace_dir.parent / "agent_y"),
                },
            ],
        )

        result = run_pool_auto_sync()

        assert result["failed"] == []
        assert result["synced"][0]["skill"] == "demo"
        assert result["synced"][0]["agents"] == ["Agent X"]
        assert (workspace_dir / "skills" / "demo" / "SKILL.md").exists()
        entry = _read_pool_manifest(pool_dir)["skills"]["demo"]
        # The stamped hash lives in the automation namespace (flat keys
        # are migrated away on write).
        assert entry["automation"]["auto_sync"]["synced_hash"]

    def test_run_sync_name_filter(self, pool_env, monkeypatch):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("demo", _skill_md("demo"))
        _write_pool_manifest(
            pool_dir,
            {
                "demo": {
                    "source": "customized",
                    "auto_update": True,
                    "auto_update_targets": ["agent_x"],
                },
            },
        )
        monkeypatch.setattr(
            skill_pool_service,
            "list_workspaces",
            lambda: [
                {
                    "agent_id": "agent_x",
                    "agent_name": "Agent X",
                    "workspace_dir": str(workspace_dir),
                },
            ],
        )

        # Filtering by another name → nothing synced.
        assert run_pool_auto_sync(skill_name="other") == {
            "synced": [],
            "failed": [],
            "checked": 0,
        }


class TestRenameBroadcast:
    def test_rename_moves_workspace_entries(self, pool_env, monkeypatch):
        # The pool has already been renamed to the new name; this call
        # migrates the workspace copies from old → new.
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("new", _skill_md("new"))
        _write_pool_manifest(pool_dir, {"new": {"source": "customized"}})
        _seed_workspace_skill(
            workspace_dir,
            "old",
            {"source": "customized", "enabled": False, "tags": ["t"]},
        )
        monkeypatch.setattr(
            skill_pool_service,
            "list_workspaces",
            lambda: [
                {
                    "agent_id": "agent_x",
                    "agent_name": "Agent X",
                    "workspace_dir": str(workspace_dir),
                },
            ],
        )

        result = service.rename_in_workspaces("old", "new")

        assert result == {"renamed": ["agent_x"], "overwritten": []}
        manifest = _read_workspace_manifest(workspace_dir)
        assert "old" not in manifest["skills"]
        new_entry = manifest["skills"]["new"]
        assert new_entry["enabled"] is False
        assert new_entry["tags"] == ["t"]
        assert not (workspace_dir / "skills" / "old").exists()
        assert (workspace_dir / "skills" / "new" / "SKILL.md").exists()

    def test_rename_same_name_is_noop(self, pool_env, monkeypatch):
        service, pool_dir, workspace_dir = pool_env
        monkeypatch.setattr(skill_registry, "list_workspaces", lambda: [])
        result = service.rename_in_workspaces("x", "x")
        assert result == {"renamed": [], "overwritten": []}

    def test_rename_bad_name_is_noop(self, pool_env, monkeypatch):
        service, pool_dir, workspace_dir = pool_env
        monkeypatch.setattr(skill_registry, "list_workspaces", lambda: [])
        result = service.rename_in_workspaces("bad/name", "new")
        assert result == {"renamed": [], "overwritten": []}

    def test_rename_source_missing_in_pool_is_noop(
        self,
        pool_env,
        monkeypatch,
    ):
        service, pool_dir, workspace_dir = pool_env
        monkeypatch.setattr(skill_registry, "list_workspaces", lambda: [])
        result = service.rename_in_workspaces("ghost", "new")
        assert result == {"renamed": [], "overwritten": []}

    def test_rename_skips_workspaces_without_old_entry(
        self,
        pool_env,
        monkeypatch,
    ):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("new", _skill_md("new"))
        _write_pool_manifest(pool_dir, {"new": {"source": "customized"}})
        monkeypatch.setattr(
            skill_pool_service,
            "list_workspaces",
            lambda: [
                {
                    "agent_id": "agent_x",
                    "agent_name": "Agent X",
                    "workspace_dir": str(workspace_dir),
                },
            ],
        )
        result = service.rename_in_workspaces("old", "new")
        assert result == {"renamed": [], "overwritten": []}

    def test_rename_respects_target_pin(self, pool_env, monkeypatch):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("new", _skill_md("new"))
        _write_pool_manifest(pool_dir, {"new": {"source": "customized"}})
        _seed_workspace_skill(
            workspace_dir,
            "old",
            {"source": "customized"},
        )
        monkeypatch.setattr(
            skill_pool_service,
            "list_workspaces",
            lambda: [
                {
                    "agent_id": "agent_x",
                    "agent_name": "Agent X",
                    "workspace_dir": str(workspace_dir),
                },
            ],
        )

        # Pinning to a different agent skips agent_x entirely.
        result = service.rename_in_workspaces("old", "new", targets=["other"])
        assert result == {"renamed": [], "overwritten": []}
        assert "old" in _read_workspace_manifest(workspace_dir)["skills"]

    def test_rename_overwrites_existing_target(self, pool_env, monkeypatch):
        service, pool_dir, workspace_dir = pool_env
        service.create_skill("new", _skill_md("new"))
        _write_pool_manifest(pool_dir, {"new": {"source": "customized"}})
        # Seed both old and new workspace skills in a single manifest.
        _write_skill_dir(workspace_dir / "skills" / "old", "old")
        _write_skill_dir(workspace_dir / "skills" / "new", "new")
        (workspace_dir / "skill.json").write_text(
            json.dumps(
                {
                    "schema_version": "workspace-skill-manifest.v1",
                    "version": 0,
                    "skills": {
                        "old": {"source": "customized"},
                        "new": {"source": "customized"},
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            skill_pool_service,
            "list_workspaces",
            lambda: [
                {
                    "agent_id": "agent_x",
                    "agent_name": "Agent X",
                    "workspace_dir": str(workspace_dir),
                },
            ],
        )

        result = service.rename_in_workspaces("old", "new")
        assert result == {"renamed": ["agent_x"], "overwritten": ["agent_x"]}

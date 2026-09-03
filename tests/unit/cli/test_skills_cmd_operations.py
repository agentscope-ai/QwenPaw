# -*- coding: utf-8 -*-
"""Supplementary tests for skills CLI install/state-change/list/uninstall.

Covers the install-selection helper, the state-change applier, the
exact-name enable/disable setter, and the info/list/uninstall commands
(workspace and pool scopes), which were previously untested.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

import qwenpaw.cli.skills_cmd as sc


def _config(profiles=None):
    from qwenpaw.config.config import Config

    cfg = Config()
    if profiles is not None:
        cfg.agents.profiles = profiles
    return cfg


def _ref(agent_id: str, workspace_dir: str):
    from qwenpaw.config.config import AgentProfileRef

    return AgentProfileRef(id=agent_id, workspace_dir=workspace_dir)


def _skill(name: str, source: str = "local", description: str = "d"):
    return SimpleNamespace(name=name, source=source, description=description)


def _manifest(skills: dict):
    return {"skills": skills}


# ---------------------------------------------------------------------------
# _install_selected_skills
# ---------------------------------------------------------------------------


class TestInstallSelectedSkills:
    def test_pool_unavailable_reports_failures(self, tmp_path):
        installed, failures = sc._install_selected_skills(
            None,
            tmp_path,
            {"a", "b"},
            set(),
        )
        assert installed == set()
        assert len(failures) == 2
        assert all("pool unavailable" in f for f in failures)

    def test_successful_install_added(self, tmp_path):
        pool_service = SimpleNamespace(
            download_to_workspace=lambda name, wd, overwrite: {
                "success": True,
            },
        )
        installed, failures = sc._install_selected_skills(
            pool_service,
            tmp_path,
            {"new_skill"},
            {"existing"},
        )
        assert installed == {"existing", "new_skill"}
        assert failures == []

    def test_failed_install_reported(self, tmp_path):
        pool_service = SimpleNamespace(
            download_to_workspace=lambda name, wd, overwrite: {
                "success": False,
                "reason": "disk full",
            },
        )
        installed, failures = sc._install_selected_skills(
            pool_service,
            tmp_path,
            {"bad"},
            set(),
        )
        assert installed == set()
        assert failures == ["install bad (disk full)"]

    def test_exception_treated_as_failure(self, tmp_path):
        def boom(name, wd, overwrite):
            raise RuntimeError("network down")

        pool_service = SimpleNamespace(download_to_workspace=boom)
        installed, failures = sc._install_selected_skills(
            pool_service,
            tmp_path,
            {"flaky"},
            set(),
        )
        assert installed == set()
        assert "network down" in failures[0]


# ---------------------------------------------------------------------------
# _apply_skill_state_changes
# ---------------------------------------------------------------------------


class TestApplySkillStateChanges:
    def test_enable_success(self):
        service = SimpleNamespace(
            enable_skill=lambda name: {"success": True},
        )
        failures = sc._apply_skill_state_changes(
            service,
            {"a"},
            enabled=True,
        )
        assert failures == []

    def test_enable_failure_reported(self):
        service = SimpleNamespace(
            enable_skill=lambda name: {
                "success": False,
                "reason": "scan blocked",
            },
        )
        failures = sc._apply_skill_state_changes(
            service,
            {"blocked"},
            enabled=True,
        )
        assert failures == ["enable blocked (scan blocked)"]

    def test_exception_treated_as_failure(self):
        def boom(name):
            raise RuntimeError("io error")

        service = SimpleNamespace(enable_skill=boom)
        failures = sc._apply_skill_state_changes(
            service,
            {"crashy"},
            enabled=True,
        )
        assert "io error" in failures[0]

    def test_disable_path(self):
        service = SimpleNamespace(
            disable_skill=lambda name: {"success": True},
        )
        failures = sc._apply_skill_state_changes(
            service,
            {"a"},
            enabled=False,
        )
        assert failures == []

    def test_sorted_deterministic(self):
        calls = []
        service = SimpleNamespace(
            enable_skill=lambda name: calls.append(name) or {"success": True},
        )
        sc._apply_skill_state_changes(
            service,
            {"z", "a", "m"},
            enabled=True,
        )
        assert calls == ["a", "m", "z"]


# ---------------------------------------------------------------------------
# _set_skills_enabled
# ---------------------------------------------------------------------------


class TestSetSkillsEnabled:
    def test_unknown_skill_raises_click_exception(self, tmp_path, monkeypatch):
        cfg = _config({"a1": _ref("a1", str(tmp_path))})
        monkeypatch.setattr(sc, "load_config", lambda: cfg)
        monkeypatch.setattr(
            sc,
            "reconcile_workspace_manifest",
            lambda wd: _manifest({"known": {}}),
        )
        monkeypatch.setattr(sc, "SkillService", lambda wd: SimpleNamespace())
        with pytest.raises(click.ClickException, match="Failed to enable"):
            sc._set_skills_enabled(("ghost",), "a1", enabled=True)

    def test_known_skill_enabled(self, tmp_path, monkeypatch):
        cfg = _config({"a1": _ref("a1", str(tmp_path))})
        monkeypatch.setattr(sc, "load_config", lambda: cfg)
        monkeypatch.setattr(
            sc,
            "reconcile_workspace_manifest",
            lambda wd: _manifest({"known": {}}),
        )
        enabled_calls = []
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                enable_skill=lambda name: enabled_calls.append(name)
                or {"success": True},
            ),
        )
        sc._set_skills_enabled(("known",), "a1", enabled=True)
        assert enabled_calls == ["known"]

    def test_duplicates_and_blanks_skipped(self, tmp_path, monkeypatch):
        cfg = _config({"a1": _ref("a1", str(tmp_path))})
        monkeypatch.setattr(sc, "load_config", lambda: cfg)
        monkeypatch.setattr(
            sc,
            "reconcile_workspace_manifest",
            lambda wd: _manifest({"known": {}}),
        )
        enabled_calls = []
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                enable_skill=lambda name: enabled_calls.append(name)
                or {"success": True},
            ),
        )
        sc._set_skills_enabled(
            ("known", "known", "  ", ""),
            "a1",
            enabled=True,
        )
        assert enabled_calls == ["known"]

    def test_disable_action(self, tmp_path, monkeypatch):
        cfg = _config({"a1": _ref("a1", str(tmp_path))})
        monkeypatch.setattr(sc, "load_config", lambda: cfg)
        monkeypatch.setattr(
            sc,
            "reconcile_workspace_manifest",
            lambda wd: _manifest({"known": {}}),
        )
        disabled_calls = []
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                disable_skill=lambda name: disabled_calls.append(name)
                or {"success": True},
            ),
        )
        sc._set_skills_enabled(("known",), "a1", enabled=False)
        assert disabled_calls == ["known"]


# ---------------------------------------------------------------------------
# info_cmd
# ---------------------------------------------------------------------------


class TestInfoCmd:
    def test_pool_scope_found(self, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: None)
        monkeypatch.setattr(sc, "reconcile_pool_manifest", lambda: {})
        monkeypatch.setattr(
            sc,
            "SkillPoolService",
            lambda: SimpleNamespace(
                list_all_skills=lambda: [_skill("mine", source="hub")],
            ),
        )
        monkeypatch.setattr(
            sc,
            "read_skill_pool_manifest",
            lambda: _manifest({"mine": {"tags": ["a", "b"]}}),
        )
        monkeypatch.setattr(
            sc,
            "resolve_pool_skill_dir",
            lambda name: Path("/pool/mine"),
        )
        monkeypatch.setattr(sc, "get_skill_pool_dir", lambda: Path("/pool"))
        runner = CliRunner()
        result = runner.invoke(sc.info_cmd, ["mine", "--pool"])
        assert result.exit_code == 0
        assert "Skill: mine" in result.output
        assert "Scope: pool" in result.output
        assert "Tags: a, b" in result.output

    def test_pool_scope_not_found(self, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: None)
        monkeypatch.setattr(sc, "reconcile_pool_manifest", lambda: {})
        monkeypatch.setattr(
            sc,
            "SkillPoolService",
            lambda: SimpleNamespace(list_all_skills=lambda: []),
        )
        runner = CliRunner()
        result = runner.invoke(sc.info_cmd, ["ghost", "--pool"])
        assert result.exit_code != 0
        assert "not found in the skill pool" in result.output

    def test_workspace_scope_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: "a1")
        monkeypatch.setattr(
            sc,
            "_get_agent_workspace",
            lambda scope: tmp_path,
        )
        monkeypatch.setattr(
            sc,
            "reconcile_workspace_manifest",
            lambda wd: _manifest({"ws_skill": {"enabled": True}}),
        )
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: _manifest(
                {"ws_skill": {"enabled": True, "channels": ["dingtalk"]}},
            ),
        )
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                list_all_skills=lambda: [_skill("ws_skill")],
            ),
        )
        monkeypatch.setattr(
            sc,
            "get_workspace_skills_dir",
            lambda wd: wd / "skills",
        )
        runner = CliRunner()
        result = runner.invoke(sc.info_cmd, ["ws_skill", "--agent-id", "a1"])
        assert result.exit_code == 0
        assert "Skill: ws_skill" in result.output
        assert "Enabled: yes" in result.output
        assert "Channels: dingtalk" in result.output

    def test_workspace_scope_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: "a1")
        monkeypatch.setattr(sc, "_get_agent_workspace", lambda scope: tmp_path)
        monkeypatch.setattr(
            sc,
            "reconcile_workspace_manifest",
            lambda wd: _manifest({}),
        )
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: _manifest({}),
        )
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(list_all_skills=lambda: []),
        )
        runner = CliRunner()
        result = runner.invoke(sc.info_cmd, ["ghost", "--agent-id", "a1"])
        assert result.exit_code != 0
        assert "not found for agent" in result.output


# ---------------------------------------------------------------------------
# list_cmd
# ---------------------------------------------------------------------------


class TestListCmd:
    def test_pool_status_rejected(self, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: None)
        runner = CliRunner()
        result = runner.invoke(
            sc.list_cmd,
            ["--pool", "--status", "enabled"],
        )
        assert result.exit_code != 0
        assert "--status is not supported with --pool" in result.output

    def test_pool_empty(self, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: None)
        monkeypatch.setattr(sc, "reconcile_pool_manifest", lambda: {})
        monkeypatch.setattr(
            sc,
            "SkillPoolService",
            lambda: SimpleNamespace(list_all_skills=lambda: []),
        )
        runner = CliRunner()
        result = runner.invoke(sc.list_cmd, ["--pool"])
        assert result.exit_code == 0
        assert "No skills found." in result.output

    def test_pool_lists_skills(self, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: None)
        monkeypatch.setattr(sc, "reconcile_pool_manifest", lambda: {})
        monkeypatch.setattr(
            sc,
            "SkillPoolService",
            lambda: SimpleNamespace(
                list_all_skills=lambda: [
                    _skill("b", source="hub"),
                    _skill("a", source="local"),
                ],
            ),
        )
        runner = CliRunner()
        result = runner.invoke(sc.list_cmd, ["--pool"])
        assert result.exit_code == 0
        assert "Total: 2 skills" in result.output
        # sorted by name
        assert result.output.index("a") < result.output.index("b")

    def test_workspace_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: "a1")
        monkeypatch.setattr(sc, "_get_agent_workspace", lambda scope: tmp_path)
        monkeypatch.setattr(
            sc,
            "reconcile_workspace_manifest",
            lambda wd: _manifest({}),
        )
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(list_all_skills=lambda: []),
        )
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: _manifest({}),
        )
        runner = CliRunner()
        result = runner.invoke(sc.list_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 0
        assert "No skills found." in result.output

    def test_workspace_filter_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: "a1")
        monkeypatch.setattr(sc, "_get_agent_workspace", lambda scope: tmp_path)
        monkeypatch.setattr(
            sc,
            "reconcile_workspace_manifest",
            lambda wd: _manifest({}),
        )
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                list_all_skills=lambda: [_skill("on"), _skill("off")],
            ),
        )
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: _manifest({"on": {"enabled": True}}),
        )
        runner = CliRunner()
        result = runner.invoke(
            sc.list_cmd,
            ["--agent-id", "a1", "--status", "enabled"],
        )
        assert result.exit_code == 0
        assert "on" in result.output
        # The filter drops the disabled skill from the table entirely.
        assert "off" not in result.output
        assert "Showing: 1 of 2 skills, 1 enabled, 0 disabled" in (
            result.output
        )

    def test_workspace_no_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p: "a1")
        monkeypatch.setattr(sc, "_get_agent_workspace", lambda scope: tmp_path)
        monkeypatch.setattr(
            sc,
            "reconcile_workspace_manifest",
            lambda wd: _manifest({}),
        )
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                list_all_skills=lambda: [_skill("only")],
            ),
        )
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: _manifest({}),
        )
        runner = CliRunner()
        result = runner.invoke(
            sc.list_cmd,
            ["--agent-id", "a1", "--status", "enabled"],
        )
        assert result.exit_code == 0
        assert "No skills match the current filters." in result.output


# ---------------------------------------------------------------------------
# uninstall_cmd
# ---------------------------------------------------------------------------


class TestUninstallCmd:
    def test_empty_name_rejected(self, monkeypatch):
        runner = CliRunner()
        result = runner.invoke(sc.uninstall_cmd, ["  "])
        assert result.exit_code != 0
        assert "cannot be empty" in result.output

    def test_workspace_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p, **kw: "a1")
        monkeypatch.setattr(sc, "_get_agent_workspace", lambda scope: tmp_path)
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: _manifest({}),
        )
        runner = CliRunner()
        result = runner.invoke(sc.uninstall_cmd, ["ghost", "--agent-id", "a1"])
        assert result.exit_code != 0
        assert "was not found" in result.output

    def test_workspace_uninstall_disabled_then_delete(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p, **kw: "a1")
        monkeypatch.setattr(sc, "_get_agent_workspace", lambda scope: tmp_path)
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: _manifest({"mine": {"enabled": True}}),
        )
        calls = []
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                disable_skill=lambda name: calls.append("disable")
                or {"success": True},
                delete_skill=lambda name: calls.append("delete") or True,
            ),
        )
        runner = CliRunner()
        result = runner.invoke(sc.uninstall_cmd, ["mine", "--agent-id", "a1"])
        assert result.exit_code == 0
        assert calls == ["disable", "delete"]
        assert "Uninstalled skill" in result.output

    def test_workspace_uninstall_enabled_disable_fails(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p, **kw: "a1")
        monkeypatch.setattr(sc, "_get_agent_workspace", lambda scope: tmp_path)
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: _manifest({"mine": {"enabled": True}}),
        )
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                disable_skill=lambda name: {"success": False},
                delete_skill=lambda name: True,
            ),
        )
        runner = CliRunner()
        result = runner.invoke(sc.uninstall_cmd, ["mine", "--agent-id", "a1"])
        assert result.exit_code != 0
        assert "Failed to disable" in result.output

    def test_pool_not_found(self, monkeypatch):
        monkeypatch.setattr(sc, "_resolve_scope", lambda a, p, **kw: None)
        monkeypatch.setattr(
            sc,
            "read_skill_pool_manifest",
            lambda: _manifest({}),
        )
        runner = CliRunner()
        result = runner.invoke(sc.uninstall_cmd, ["ghost", "--pool"])
        assert result.exit_code != 0
        assert "not found" in result.output

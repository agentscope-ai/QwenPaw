# -*- coding: utf-8 -*-
# pylint: disable=reimported,protected-access,unused-argument,unused-import
"""Unit tests for cli/skills_cmd.py helpers and commands.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the skills CLI helpers
and click commands, which previously had zero unit-test coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

import qwenpaw.cli.skills_cmd as sc


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: d for {name}\n---\n# body\n"


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
# _get_agent_workspace
# ---------------------------------------------------------------------------


class TestGetAgentWorkspace:
    def test_resolves_known_agent(self, tmp_path, monkeypatch):
        cfg = _config({"a1": _ref("a1", str(tmp_path / "ws"))})
        monkeypatch.setattr(sc, "load_config", lambda: cfg)
        assert sc._get_agent_workspace("a1") == tmp_path / "ws"

    def test_empty_id_rejected(self):
        with pytest.raises(click.ClickException, match="cannot be empty"):
            sc._get_agent_workspace("   ")

    def test_config_load_failure(self, monkeypatch):
        monkeypatch.setattr(
            sc,
            "load_config",
            lambda: (_ for _ in ()).throw(RuntimeError("bad")),
        )
        with pytest.raises(click.ClickException, match="Failed to load"):
            sc._get_agent_workspace("a1")

    def test_unknown_agent_lists_available(self, monkeypatch):
        cfg = _config({"a1": _ref("a1", "/tmp/x"), "a2": _ref("a2", "/tmp/y")})
        monkeypatch.setattr(sc, "load_config", lambda: cfg)
        with pytest.raises(click.ClickException, match="a1, a2"):
            sc._get_agent_workspace("ghost")

    def test_unknown_agent_no_profiles(self, monkeypatch):
        monkeypatch.setattr(sc, "load_config", lambda: _config({}))
        with pytest.raises(click.ClickException, match="not found"):
            sc._get_agent_workspace("ghost")


class TestRaiseConflict:
    def test_with_suggested_name(self):
        exc = sc.SkillConflictError(
            {"message": "taken", "suggested_name": "demo-2"},
        )
        with pytest.raises(click.ClickException, match="demo-2"):
            sc._raise_conflict(exc)

    def test_without_detail(self):
        exc = sc.SkillConflictError({"message": "plain failure"})
        with pytest.raises(click.ClickException, match="plain failure"):
            sc._raise_conflict(exc)


class TestPrintSkillChanges:
    def test_prints_all_sections(self, capsys):
        sc._print_skill_changes({"b", "a"}, {"c"}, {"d"})
        out = capsys.readouterr().out
        assert "Install: a, b" in out
        assert "Enable:" in out
        assert "Disable:" in out

    def test_empty_sets_print_nothing(self, capsys):
        sc._print_skill_changes(set(), set(), set())
        assert capsys.readouterr().out.strip() == ""


class TestValidateSkillFrontmatter:
    def test_missing_skill_md(self, tmp_path):
        with pytest.raises(click.ClickException, match="Missing SKILL.md"):
            sc._validate_skill_frontmatter(tmp_path)

    def test_valid_skill_passes(self, tmp_path):
        (tmp_path / "SKILL.md").write_text(_skill_md("demo"), encoding="utf-8")
        sc._validate_skill_frontmatter(tmp_path)  # no raise

    def test_invalid_frontmatter(self, tmp_path):
        (tmp_path / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
        with pytest.raises(click.ClickException):
            sc._validate_skill_frontmatter(tmp_path)


class TestResolveScope:
    def test_agent_id_default(self):
        assert sc._resolve_scope(None, False) == "default"
        assert sc._resolve_scope("a1", False) == "a1"

    def test_pool_flag_returns_none(self):
        assert sc._resolve_scope(None, True) is None

    def test_pool_and_agent_conflict(self):
        with pytest.raises(click.ClickException, match="mutually exclusive"):
            sc._resolve_scope("a1", True)

    def test_default_pool_fallback(self):
        assert sc._resolve_scope(None, False, default_pool=True) is None
        assert sc._resolve_scope("a1", False, default_pool=True) == "a1"


class TestResolveSkillTestDir:
    def test_path_takes_precedence(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        result = sc._resolve_skill_test_dir(str(skill_dir), None)
        assert result == skill_dir.resolve()

    def test_workspace_name_resolution(self, tmp_path, monkeypatch):
        cfg = _config({"default": _ref("default", str(tmp_path / "ws"))})
        monkeypatch.setattr(sc, "load_config", lambda: cfg)
        result = sc._resolve_skill_test_dir("demo", None)
        assert result == tmp_path / "ws" / "skills" / "demo"

    def test_pool_resolution(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "reconcile_pool_manifest", lambda: {})
        pool_dir = tmp_path / "skill_pool"
        (pool_dir / "demo").mkdir(parents=True)
        monkeypatch.setattr(
            sc,
            "resolve_pool_skill_dir",
            lambda name: pool_dir / name,
        )
        result = sc._resolve_skill_test_dir("demo", None, pool=True)
        assert result == pool_dir / "demo"

    def test_pool_missing_falls_back_to_pool_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "reconcile_pool_manifest", lambda: {})
        monkeypatch.setattr(sc, "resolve_pool_skill_dir", lambda name: None)
        pool_dir = tmp_path / "skill_pool"
        monkeypatch.setattr(sc, "get_skill_pool_dir", lambda: pool_dir)
        result = sc._resolve_skill_test_dir("demo", None, pool=True)
        assert result == pool_dir / "demo"


class TestRunSkillTest:
    def test_missing_dir(self, tmp_path):
        with pytest.raises(click.ClickException, match="not found"):
            sc._run_skill_test(tmp_path / "missing")

    def test_valid_skill_returns_name(self, tmp_path):
        skill_dir = tmp_path / "demo"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            _skill_md("demo"),
            encoding="utf-8",
        )

        from types import SimpleNamespace

        import qwenpaw.cli.skills_cmd as sc_mod

        result = SimpleNamespace(is_safe=True, findings=[])
        original = sc_mod.scan_skill_directory
        sc_mod.scan_skill_directory = lambda *a, **kw: result
        try:
            assert sc._run_skill_test(skill_dir) == "demo"
        finally:
            sc_mod.scan_skill_directory = original

    def test_unsafe_scan_raises(self, tmp_path):
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(_skill_md("bad"), encoding="utf-8")

        from types import SimpleNamespace

        result = SimpleNamespace(is_safe=False, findings=[object()])
        original = sc.scan_skill_directory
        sc.scan_skill_directory = lambda *a, **kw: result
        try:
            with pytest.raises(click.ClickException, match="issue\\(s\\)"):
                sc._run_skill_test(skill_dir)
        finally:
            sc.scan_skill_directory = original

    def test_scan_blocked_raises(self, tmp_path):
        skill_dir = tmp_path / "blocked"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            _skill_md("blocked"),
            encoding="utf-8",
        )

        def boom(*a, **kw):
            raise sc.SkillScanError(
                __import__("types").SimpleNamespace(
                    skill_name="blocked",
                    findings=[],
                    max_severity=None,
                ),
            )

        original = sc.scan_skill_directory
        sc.scan_skill_directory = boom
        try:
            with pytest.raises(click.ClickException):
                sc._run_skill_test(skill_dir)
        finally:
            sc.scan_skill_directory = original


# ---------------------------------------------------------------------------
# click commands (list / enable / disable)
# ---------------------------------------------------------------------------


class TestListCmd:
    def test_list_pool_skills(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            sc,
            "_resolve_scope",
            lambda agent_id, pool, **kw: None,
        )
        monkeypatch.setattr(sc, "reconcile_pool_manifest", lambda: {})
        pool_service = SimpleNamespace(
            list_all_skills=lambda: [
                SimpleNamespace(name="demo", source="customized"),
            ],
        )
        monkeypatch.setattr(
            sc,
            "SkillPoolService",
            lambda: pool_service,
        )
        result = CliRunner().invoke(sc.skills_group, ["list", "--pool"])
        assert result.exit_code == 0
        assert "demo" in result.output
        assert "Total: 1 skills" in result.output

    def test_list_pool_empty(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            sc,
            "_resolve_scope",
            lambda agent_id, pool, **kw: None,
        )
        monkeypatch.setattr(sc, "reconcile_pool_manifest", lambda: {})
        monkeypatch.setattr(
            sc,
            "SkillPoolService",
            lambda: SimpleNamespace(list_all_skills=lambda: []),
        )
        result = CliRunner().invoke(sc.skills_group, ["list", "--pool"])
        assert result.exit_code == 0
        assert "No skills found." in result.output

    def test_list_pool_status_filter_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            sc,
            "_resolve_scope",
            lambda agent_id, pool, **kw: None,
        )
        result = CliRunner().invoke(
            sc.skills_group,
            ["list", "--pool", "--status", "enabled"],
        )
        assert result.exit_code != 0
        assert "not supported" in result.output

    def test_list_workspace_skills(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            sc,
            "_resolve_scope",
            lambda agent_id, pool, **kw: "default",
        )
        monkeypatch.setattr(
            sc,
            "_get_agent_workspace",
            lambda agent_id: tmp_path / "ws",
        )
        monkeypatch.setattr(sc, "reconcile_workspace_manifest", lambda wd: {})
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                list_all_skills=lambda: [
                    SimpleNamespace(name="demo", source="customized"),
                ],
            ),
        )
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: {"skills": {"demo": {"enabled": True}}},
        )
        result = CliRunner().invoke(sc.skills_group, ["list"])
        assert result.exit_code == 0
        assert "demo" in result.output

    def test_list_workspace_empty(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            sc,
            "_resolve_scope",
            lambda agent_id, pool, **kw: "default",
        )
        monkeypatch.setattr(
            sc,
            "_get_agent_workspace",
            lambda agent_id: tmp_path / "ws",
        )
        monkeypatch.setattr(sc, "reconcile_workspace_manifest", lambda wd: {})
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(list_all_skills=lambda: []),
        )
        result = CliRunner().invoke(sc.skills_group, ["list"])
        assert result.exit_code == 0
        assert "No skills found." in result.output

    def test_list_workspace_status_filter_no_match(
        self,
        tmp_path,
        monkeypatch,
    ):
        from types import SimpleNamespace

        monkeypatch.setattr(
            sc,
            "_resolve_scope",
            lambda agent_id, pool, **kw: "default",
        )
        monkeypatch.setattr(
            sc,
            "_get_agent_workspace",
            lambda agent_id: tmp_path / "ws",
        )
        monkeypatch.setattr(sc, "reconcile_workspace_manifest", lambda wd: {})
        monkeypatch.setattr(
            sc,
            "SkillService",
            lambda wd: SimpleNamespace(
                list_all_skills=lambda: [
                    SimpleNamespace(name="demo", source="customized"),
                ],
            ),
        )
        monkeypatch.setattr(
            sc,
            "read_skill_manifest",
            lambda wd: {"skills": {"demo": {"enabled": True}}},
        )
        result = CliRunner().invoke(
            sc.skills_group,
            ["list", "--status", "disabled"],
        )
        assert result.exit_code == 0
        assert "No skills match the current filters." in result.output

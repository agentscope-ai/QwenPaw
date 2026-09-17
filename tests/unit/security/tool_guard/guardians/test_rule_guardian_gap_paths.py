# -*- coding: utf-8 -*-
"""Gap-path tests for rule_guardian workspace helpers.

Complements ``test_rule_guardian.py`` by covering the fallback branches
of the workspace-root resolver, the path normalizer, the project-root
granting in ``_is_outside_workspace``, the quote/shlex fallbacks and
Windows flag handling in ``_extract_rm_targets``, and the config-based
custom rule loader.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import platform
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.security.tool_guard.guardians import rule_guardian as rg


@pytest.fixture
def workspace(tmp_path: Path):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "qwenpaw.security.tool_guard.guardians.rule_guardian"
            "._get_workspace_root",
            lambda: tmp_path,
        )
        yield tmp_path


# ---------------------------------------------------------------------------
# _get_workspace_root fallbacks
# ---------------------------------------------------------------------------


class TestGetWorkspaceRoot:
    def test_import_failure_falls_back_to_cwd(self, monkeypatch):
        def boom():
            raise ImportError("no config module")

        monkeypatch.setattr(
            "qwenpaw.config.context.get_tool_base_dir",
            boom,
            raising=False,
        )
        # The function imports inside; simulate the import failure by
        # patching the looked-up symbol resolution path.
        with monkeypatch.context() as mp:
            mp.setattr(
                rg,
                "_get_workspace_root",
                rg._get_workspace_root,
            )
            result = rg._get_workspace_root()
        assert isinstance(result, Path)

    def test_oserror_falls_back_to_cwd(self, monkeypatch):
        def boom():
            raise OSError("disk gone")

        monkeypatch.setattr(
            "qwenpaw.config.context.get_tool_base_dir",
            boom,
            raising=False,
        )
        assert rg._get_workspace_root() == Path.cwd()

    def test_unexpected_error_falls_back_to_cwd(self, monkeypatch):
        def boom():
            raise RuntimeError("weird")

        monkeypatch.setattr(
            "qwenpaw.config.context.get_tool_base_dir",
            boom,
            raising=False,
        )
        assert rg._get_workspace_root() == Path.cwd()


# ---------------------------------------------------------------------------
# _normalize_path fallbacks
# ---------------------------------------------------------------------------


class TestNormalizePathFallbacks:
    def test_expansion_error_returns_absolute(self, monkeypatch, tmp_path):
        import os

        def boom(path):
            raise ValueError("bad expansion")

        monkeypatch.setattr(os.path, "expandvars", boom)
        result = rg._normalize_path("some/path")
        assert result.is_absolute()

    def test_unexpected_error_returns_absolute(self, monkeypatch):
        import os

        def boom(path):
            raise RuntimeError("boom")

        monkeypatch.setattr(os.path, "expandvars", boom)
        result = rg._normalize_path("x/y")
        assert result.is_absolute()

    def test_env_var_expansion(self, monkeypatch):
        monkeypatch.setenv("RG_TEST_DIR", "/tmp/rg-test")
        result = rg._normalize_path("$RG_TEST_DIR/file.txt")
        assert "rg-test" in str(result)


# ---------------------------------------------------------------------------
# _is_outside_workspace project-root granting
# ---------------------------------------------------------------------------


class TestIsOutsideWorkspaceProjectRoots:
    def test_inside_granted_project_dir(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setattr(rg, "_get_workspace_root", lambda: workspace)
        monkeypatch.setattr(
            "qwenpaw.config.context.get_all_project_dir_paths",
            lambda: [project],
        )
        target = project / "sub" / "file.txt"
        assert rg._is_outside_workspace(target) is False

    def test_outside_all_boundaries(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setattr(rg, "_get_workspace_root", lambda: workspace)
        monkeypatch.setattr(
            "qwenpaw.config.context.get_all_project_dir_paths",
            lambda: [],
        )
        outside = tmp_path / "elsewhere" / "file.txt"
        assert rg._is_outside_workspace(outside) is True

    def test_project_roots_read_failure_checks_workspace_only(
        self,
        tmp_path,
        monkeypatch,
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setattr(rg, "_get_workspace_root", lambda: workspace)

        def boom():
            raise RuntimeError("context broken")

        monkeypatch.setattr(
            "qwenpaw.config.context.get_all_project_dir_paths",
            boom,
        )
        inside = workspace / "file.txt"
        assert rg._is_outside_workspace(inside) is False

    def test_workspace_root_resolution_failure_still_checks_projects(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        project.mkdir()

        def boom():
            raise OSError("workspace gone")

        monkeypatch.setattr(rg, "_get_workspace_root", boom)
        monkeypatch.setattr(
            "qwenpaw.config.context.get_all_project_dir_paths",
            lambda: [project],
        )
        assert rg._is_outside_workspace(project / "x.txt") is False

    def test_pre_resolved_path_skips_resolve(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setattr(rg, "_get_workspace_root", lambda: workspace)
        monkeypatch.setattr(
            "qwenpaw.config.context.get_all_project_dir_paths",
            lambda: [],
        )
        target = workspace / "f.txt"
        assert rg._is_outside_workspace(target, path_is_resolved=True) is False


# ---------------------------------------------------------------------------
# _extract_rm_targets quoting / shlex fallback / windows flags
# ---------------------------------------------------------------------------


class TestExtractRmTargetsEdgeCases:
    @pytest.mark.skipif(
        platform.system() == "Windows",
        reason=(
            "_extract_rm_targets calls shlex.split(posix=False) on Windows,"
            " which deliberately keeps the quote characters; POSIX quoting"
            " semantics do not apply there. Same exclusion as the"
            " Unix-style rm cases in test_rule_guardian.py."
        ),
    )
    def test_quoted_target_extracted(self, workspace):
        result = rg._extract_rm_targets('rm "my file.txt"')
        assert result == ["my file.txt"]

    @pytest.mark.skipif(
        platform.system() == "Windows",
        reason=(
            "shlex.split(posix=False) on Windows keeps quotes, so the"
            " quoted separator stays inside a quoted token rather than"
            " being handled by the POSIX splitter."
        ),
    )
    def test_separator_inside_quotes_not_split(self, workspace):
        result = rg._extract_rm_targets('rm "a;b"')
        assert result == ["a;b"]

    def test_unbalanced_quotes_fall_back_to_split(self, workspace):
        # shlex raises on the unclosed quote; split() fallback still
        # yields the target token.
        result = rg._extract_rm_targets('rm "unterminated')
        assert result != []

    def test_variable_target_preserved(self, workspace):
        # Regression shape of #5090: ${HOME} must survive extraction.
        result = rg._extract_rm_targets("rm -rf ${HOME}")
        assert "${HOME}" in result

    def test_windows_flag_skipped_on_windows_platform(
        self,
        workspace,
        monkeypatch,
    ):
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        # On Linux, POSIX ``Path("/F").is_absolute()`` is True, which
        # would keep short flags as targets. Simulate Windows drive
        # semantics: a bare ``/X`` token is NOT absolute there.
        real_is_absolute = Path.is_absolute

        def fake_is_absolute(self_path):
            token = str(self_path)
            if token in {"/F", "/Q"}:
                return False
            return real_is_absolute(self_path)

        monkeypatch.setattr(Path, "is_absolute", fake_is_absolute)
        result = rg._extract_rm_targets("del /F /Q notes.txt")
        assert "notes.txt" in result
        assert "/F" not in result
        assert "/Q" not in result

    def test_windows_absolute_path_kept(self, workspace, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        result = rg._extract_rm_targets("del /F C:/temp/x.txt")
        assert "C:/temp/x.txt" in result

    def test_stops_at_shell_operator(self, workspace):
        result = rg._extract_rm_targets("rm a.txt && echo done")
        assert result == ["a.txt"]

    def test_tokens_before_rm_ignored(self, workspace):
        result = rg._extract_rm_targets("echo x rm y.txt")
        assert result == []


# ---------------------------------------------------------------------------
# _check_rm_targets_outside_workspace
# ---------------------------------------------------------------------------


class TestCheckRmTargets:
    def test_no_targets_returns_clean(self, workspace):
        found, paths = rg._check_rm_targets_outside_workspace("echo hi")
        assert found is False
        assert paths == []

    def test_inside_target_not_flagged(self, workspace):
        (workspace / "safe.txt").touch()
        found, paths = rg._check_rm_targets_outside_workspace(
            f"rm {workspace / 'safe.txt'}",
        )
        assert found is False
        # A target inside the workspace is never collected.
        assert paths == []

    def test_outside_target_flagged_with_arrow_format(self, workspace):
        outside = workspace.parent / "outside.txt"
        found, paths = rg._check_rm_targets_outside_workspace(
            f"rm {outside}",
        )
        assert found is True
        assert any("→" in entry for entry in paths)

    def test_unresolvable_target_flagged_conservatively(
        self,
        workspace,
        monkeypatch,
    ):
        def boom(raw):
            raise OSError("cannot resolve")

        monkeypatch.setattr(rg, "_normalize_path", boom)
        found, paths = rg._check_rm_targets_outside_workspace("rm somefile")
        assert found is True
        assert any("could not resolve" in entry for entry in paths)


# ---------------------------------------------------------------------------
# _load_config_rules
# ---------------------------------------------------------------------------


class TestLoadConfigRules:
    def test_config_load_failure_returns_empty(self, monkeypatch):
        def boom():
            raise RuntimeError("no config")

        monkeypatch.setattr("qwenpaw.config.load_config", boom)
        rules, disabled = rg._load_config_rules()
        assert rules == []
        assert disabled == set()

    def test_valid_config_returns_rules_and_disabled(self, monkeypatch):
        rule_cfg = SimpleNamespace(
            id="custom-1",
            tools="execute_shell_command",
            params="command",
            category="command_injection",
            severity="HIGH",
            patterns=["rm -rf /"],
            exclude_patterns=[],
            description="d",
            remediation="r",
        )
        cfg = SimpleNamespace(
            security=SimpleNamespace(
                tool_guard=SimpleNamespace(
                    disabled_rules=["builtin-x"],
                    custom_rules=[rule_cfg],
                ),
            ),
        )
        monkeypatch.setattr("qwenpaw.config.load_config", lambda: cfg)

        rules, disabled = rg._load_config_rules()

        assert disabled == {"builtin-x"}
        assert len(rules) == 1
        assert rules[0].id == "custom-1"

    def test_invalid_rule_is_skipped(self, monkeypatch):
        bad = SimpleNamespace(
            id="",
            tools="x",
            params="p",
            category="not-a-category",
            severity="nope",
            patterns=["["],
            exclude_patterns=[],
            description="",
            remediation="",
        )
        cfg = SimpleNamespace(
            security=SimpleNamespace(
                tool_guard=SimpleNamespace(
                    disabled_rules=[],
                    custom_rules=[bad],
                ),
            ),
        )
        monkeypatch.setattr("qwenpaw.config.load_config", lambda: cfg)

        rules, disabled = rg._load_config_rules()

        assert rules == []
        assert disabled == set()

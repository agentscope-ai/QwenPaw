# -*- coding: utf-8 -*-
"""Tests for PluginLoader dependency probing and uv discovery.

Covers the static helpers that decide whether a requirement is already
satisfied (metadata probe + import probe) and locate the ``uv`` binary,
which previously had no unit coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path


from qwenpaw.plugins.loader import PluginLoader


# ---------------------------------------------------------------------------
# _is_requirement_satisfied
# ---------------------------------------------------------------------------


class TestIsRequirementSatisfied:
    def test_installed_package_no_specifier(self):
        from packaging.requirements import Requirement

        # ``packaging`` is a hard dependency, always present.
        req = Requirement("packaging")
        assert PluginLoader._is_requirement_satisfied(req) is True

    def test_installed_package_satisfying_specifier(self):
        from packaging.requirements import Requirement

        req = Requirement("packaging>=1.0")
        assert PluginLoader._is_requirement_satisfied(req) is True

    def test_installed_package_violating_specifier(self):
        from packaging.requirements import Requirement

        # Require an impossibly high version of a real package.
        req = Requirement("packaging>=9999.0")
        assert PluginLoader._is_requirement_satisfied(req) is False

    def test_missing_package_no_specifier(self):
        from packaging.requirements import Requirement

        req = Requirement("this-package-does-not-exist-xyz")
        assert PluginLoader._is_requirement_satisfied(req) is False

    def test_missing_package_with_specifier(self):
        from packaging.requirements import Requirement

        req = Requirement("this-package-does-not-exist-xyz>=1.0")
        assert PluginLoader._is_requirement_satisfied(req) is False

    def test_frozen_bundled_via_import_probe(self):
        """A package present in the env but lacking .dist-info is found.

        The import probe covers frozen desktop builds where dist-info is
        stripped (issue #5209). We simulate by checking a module that is
        importable in this test process.
        """
        from packaging.requirements import Requirement

        # ``json`` is a stdlib module with no dist-info.
        req = Requirement("json")
        assert PluginLoader._is_requirement_satisfied(req) is True


# ---------------------------------------------------------------------------
# _find_unsatisfied_dependencies
# ---------------------------------------------------------------------------


class TestFindUnsatisfiedDependencies:
    def test_missing_requirements_file_returns_empty(self, tmp_path):
        result = PluginLoader._find_unsatisfied_dependencies(
            tmp_path / "requirements.txt",
        )
        assert result == []

    def test_all_satisfied_returns_empty(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("packaging\n", encoding="utf-8")
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == []

    def test_missing_package_reported(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "this-package-does-not-exist-xyz>=1.0\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == ["this-package-does-not-exist-xyz>=1.0"]

    def test_comments_and_blanks_skipped(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "# a comment\n\npackaging\n   \n-r extra.txt\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == []

    def test_option_lines_skipped(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "--index-url https://example.com\npackaging\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == []

    def test_malformed_line_skipped_not_raised(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "not a valid requirement !!!\npackaging\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == []

    def test_mixed_satisfied_and_missing(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "packaging\nthis-missing-one-abc\n",
            encoding="utf-8",
        )
        result = PluginLoader._find_unsatisfied_dependencies(req_file)
        assert result == ["this-missing-one-abc"]


# ---------------------------------------------------------------------------
# _find_uv
# ---------------------------------------------------------------------------


class TestFindUv:
    def test_found_on_path(self, monkeypatch):
        monkeypatch.setattr(
            "qwenpaw.plugins.loader.shutil.which",
            lambda name: "/usr/local/bin/uv" if name == "uv" else None,
        )
        assert PluginLoader._find_uv() == "/usr/local/bin/uv"

    def test_not_on_path_falls_back_to_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "qwenpaw.plugins.loader.shutil.which",
            lambda name: None,
        )
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        uv_bin = home / ".local" / "bin" / "uv"
        uv_bin.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert PluginLoader._find_uv() == str(uv_bin)

    def test_not_found_anywhere_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "qwenpaw.plugins.loader.shutil.which",
            lambda name: None,
        )
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert PluginLoader._find_uv() is None

    def test_windows_localappdata_candidate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "qwenpaw.plugins.loader.shutil.which",
            lambda name: None,
        )
        home = tmp_path / "home"
        home.mkdir()
        local_app = tmp_path / "localapp"
        uv_exe = local_app / "Programs" / "uv" / "uv.exe"
        uv_exe.parent.mkdir(parents=True)
        uv_exe.write_text("MZ", encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        monkeypatch.setenv("LOCALAPPDATA", str(local_app))
        assert PluginLoader._find_uv() == str(uv_exe)

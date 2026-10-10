# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unnecessary-lambda,unused-argument  # noqa: E501
"""Unit tests for plugins/loader.py helper functions.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the plugin loader path /
runtime-dir helpers which previously sat at ~53% coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import qwenpaw.plugins.loader as pl


@pytest.fixture()
def working_dir(tmp_path, monkeypatch):
    wd = tmp_path / "wd"
    wd.mkdir()
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", wd)
    return wd


class TestIsFrozen:
    def test_not_frozen(self):
        assert pl._is_frozen() is False

    def test_frozen_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert pl._is_frozen() is True


class TestDesktopPython:
    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("QWENPAW_DESKTOP_PY_RUNTIME", raising=False)
        assert pl._desktop_python() is None

    def test_blank_returns_none(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", "   ")
        assert pl._desktop_python() is None

    def test_missing_file_returns_none(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", "/no/such/python")
        assert pl._desktop_python() is None

    def test_existing_file_returned(self, tmp_path, monkeypatch):
        py = tmp_path / "python"
        py.write_text("")
        monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", str(py))
        assert pl._desktop_python() == str(py)


class TestPluginRuntimeDirs:
    def test_runtime_dir_under_working_dir(self, working_dir):
        assert pl._plugin_runtime_dir() == working_dir / "plugin_runtime"

    def test_site_dir_bucketed_and_created(self, working_dir):
        site = pl._plugin_site_dir()
        assert site.is_dir()
        assert site.name == "site"
        assert f"py{sys.version_info.major}.{sys.version_info.minor}" in (
            str(site)
        )

    def test_install_lock_path_sanitised(self, working_dir):
        lock = pl._install_lock_path("my plugin/id")
        assert lock.name == "my_plugin_id.lock"
        assert lock.parent == working_dir / "plugin_runtime" / "install-locks"

    def test_install_lock_path_simple(self, working_dir):
        lock = pl._install_lock_path("demo-1.0")
        assert lock.name == "demo-1.0.lock"


class TestNormRealpath:
    def test_normalises(self, tmp_path):
        assert pl._norm_realpath(tmp_path) == pl._norm_realpath(str(tmp_path))


class TestResolvedPluginManifestPath:
    def test_returns_manifest(self, tmp_path):
        (tmp_path / "plugin.json").write_text("{}")
        result = pl.resolved_plugin_manifest_path(tmp_path)
        assert result.name == "plugin.json"

    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            pl.resolved_plugin_manifest_path(tmp_path / "nope")

    def test_missing_manifest_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            pl.resolved_plugin_manifest_path(tmp_path)

    def test_symlink_escape_rejected(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        outside = tmp_path / "outside" / "plugin.json"
        outside.parent.mkdir()
        outside.write_text("{}")
        (src / "plugin.json").symlink_to(outside)
        with pytest.raises(ValueError, match="escapes"):
            pl.resolved_plugin_manifest_path(src)


class TestIsDisabledPluginDir:
    def test_hidden_dir_disabled(self):
        assert pl._is_disabled_plugin_dir(Path("/x/.git")) is True

    def test_disabled_suffix(self):
        assert pl._is_disabled_plugin_dir(Path("/x/remote.disabled")) is True

    def test_normal_dir_enabled(self):
        assert pl._is_disabled_plugin_dir(Path("/x/remote")) is False


class TestEnsurePluginSiteOnPath:
    def test_noop_when_not_frozen(self, monkeypatch):
        monkeypatch.setattr(pl, "_is_frozen", lambda: False)
        pl._ensure_plugin_site_on_path()  # must not raise or modify path

    def test_adds_site_when_frozen(self, working_dir, monkeypatch):
        monkeypatch.setattr(pl, "_is_frozen", lambda: True)
        site_dir = pl._plugin_site_dir()
        # clean the dir from sys.path so the insertion path is exercised
        monkeypatch.setattr(
            pl.sys,
            "path",
            [p for p in pl.sys.path if p != str(site_dir)],
        )
        import site as _site

        adds = []
        monkeypatch.setattr(_site, "addsitedir", lambda d: adds.append(d))
        pl._ensure_plugin_site_on_path()
        assert str(site_dir) in pl.sys.path
        assert pl.os.environ.get("QWENPAW_PLUGIN_SITE") == str(site_dir)

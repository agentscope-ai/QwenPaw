# -*- coding: utf-8 -*-
"""Tests for PawApp router helpers.

Covers _build_app_info normalization, _load_plugin_json (missing /
malformed), _scan_installed_apps_fallback directory scanning, and
_get_pawapps_from_registry, which previously had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


from qwenpaw.app.routers import pawapps as pa


def _manifest(**meta_pawapp):
    return {
        "id": "app-1",
        "name": "My App",
        "version": "1.0.0",
        "description": "A test app",
        "author": "tester",
        "meta": {"pawapp": meta_pawapp},
    }


# ---------------------------------------------------------------------------
# _build_app_info
# ---------------------------------------------------------------------------


class TestBuildAppInfo:
    def test_full_manifest(self):
        manifest = _manifest(category="tools", icon="app.svg", entry_page="/")
        info = pa._build_app_info(manifest)
        assert info["id"] == "app-1"
        assert info["name"] == "My App"
        assert info["category"] == "tools"
        assert info["entry_page"] == "/"
        assert info["status"] == "installed"
        assert info["launch_scope"] == "page"

    def test_missing_fields_default(self):
        info = pa._build_app_info({}, fallback_id="dir-name")
        assert info["id"] == "dir-name"
        assert info["name"] == "dir-name"
        assert info["version"] == "0.0.0"
        assert info["category"] == ""

    def test_pawapp_meta_absent(self):
        manifest = {"id": "x", "meta": {}}
        info = pa._build_app_info(manifest)
        assert info["launch_scope"] == "page"
        assert info["icon"] == ""

    def test_settings_extracted(self):
        manifest = _manifest()
        manifest["meta"]["settings"] = [{"key": "api_key"}]
        info = pa._build_app_info(manifest)
        assert info["settings"] == [{"key": "api_key"}]

    def test_description_i18n_default_empty_dict(self):
        info = pa._build_app_info({"id": "x"})
        assert info["description_i18n"] == {}


# ---------------------------------------------------------------------------
# _load_plugin_json
# ---------------------------------------------------------------------------


class TestLoadPluginJson:
    def test_valid_manifest_loaded(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"id": "p1", "meta": {"pawapp": True}}),
            encoding="utf-8",
        )
        result = pa._load_plugin_json(plugin_dir)
        assert result is not None
        assert result["id"] == "p1"

    def test_missing_manifest_returns_none(self, tmp_path):
        plugin_dir = tmp_path / "empty"
        plugin_dir.mkdir()
        assert pa._load_plugin_json(plugin_dir) is None

    def test_malformed_json_returns_none(self, tmp_path):
        plugin_dir = tmp_path / "bad"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text("{broken", encoding="utf-8")
        assert pa._load_plugin_json(plugin_dir) is None


# ---------------------------------------------------------------------------
# _scan_installed_apps_fallback
# ---------------------------------------------------------------------------


class TestScanInstalledAppsFallback:
    def _write_pawapp(self, apps_dir: Path, name: str, manifest: dict):
        d = apps_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "plugin.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        return d

    def test_empty_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pa, "_get_apps_dir", lambda: tmp_path / "none")
        assert pa._scan_installed_apps_fallback() == []

    def test_pawapp_detected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pa, "_get_apps_dir", lambda: tmp_path)
        self._write_pawapp(
            tmp_path,
            "myapp",
            _manifest(category="tools"),
        )
        apps = pa._scan_installed_apps_fallback()
        assert len(apps) == 1
        assert apps[0]["name"] == "My App"

    def test_non_pawapp_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pa, "_get_apps_dir", lambda: tmp_path)
        self._write_pawapp(
            tmp_path,
            "regular",
            {"id": "regular", "meta": {}},
        )
        assert pa._scan_installed_apps_fallback() == []

    def test_files_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pa, "_get_apps_dir", lambda: tmp_path)
        (tmp_path / "stray.json").write_text("{}", encoding="utf-8")
        assert pa._scan_installed_apps_fallback() == []

    def test_no_manifest_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pa, "_get_apps_dir", lambda: tmp_path)
        (tmp_path / "nomanifest").mkdir()
        assert pa._scan_installed_apps_fallback() == []

    def test_missing_meta_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pa, "_get_apps_dir", lambda: tmp_path)
        self._write_pawapp(tmp_path, "nometa", {"id": "x"})
        assert pa._scan_installed_apps_fallback() == []


# ---------------------------------------------------------------------------
# _get_pawapps_from_registry
# ---------------------------------------------------------------------------


class TestGetPawappsFromRegistry:
    def _request_with_registry(self, manifests):
        registry = SimpleNamespace(
            get_all_plugin_manifests=lambda: manifests,
        )
        return SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(plugin_registry=registry),
            ),
        )

    def test_no_registry_returns_empty(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        assert pa._get_pawapps_from_registry(request) == []

    def test_pawapps_listed(self):
        request = self._request_with_registry(
            {"app-1": _manifest(category="tools")},
        )
        apps = pa._get_pawapps_from_registry(request)
        assert len(apps) == 1
        assert apps[0]["category"] == "tools"

    def test_non_pawapp_filtered(self):
        request = self._request_with_registry(
            {"regular": {"id": "regular", "meta": {}}},
        )
        assert pa._get_pawapps_from_registry(request) == []

    def test_non_dict_manifest_filtered(self):
        request = self._request_with_registry({"bad": "not-a-dict"})
        assert pa._get_pawapps_from_registry(request) == []

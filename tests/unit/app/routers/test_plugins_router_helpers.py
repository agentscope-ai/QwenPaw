# -*- coding: utf-8 -*-
"""Tests for plugin router helpers: safe zip extraction, plugin dir
discovery, disk-based plugin listing, and plugin UI file serving.

These cover the path-traversal guards and the pre-loader fallback
paths that previously had no test coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from qwenpaw.app.routers.plugins import (
    _find_plugin_dir,
    _list_plugins_from_disk,
    _safe_extract_zip,
    router as plugins_router,
)


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# _safe_extract_zip
# ---------------------------------------------------------------------------


class TestSafeExtractZip:
    def test_normal_members_extract(self, tmp_path):
        dest = tmp_path / "out"
        dest.mkdir()
        data = _zip_bytes({"a.txt": "A", "sub/b.txt": "B"})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            _safe_extract_zip(zf, dest)
        assert (dest / "a.txt").read_text(encoding="utf-8") == "A"
        assert (dest / "sub" / "b.txt").read_text(encoding="utf-8") == "B"

    def test_zip_slip_member_rejected(self, tmp_path):
        dest = tmp_path / "out"
        dest.mkdir()
        data = _zip_bytes({"../escape.txt": "evil"})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with pytest.raises(ValueError, match="Zip Slip"):
                _safe_extract_zip(zf, dest)
        assert not (tmp_path / "escape.txt").exists()

    def test_absolute_member_rejected(self, tmp_path):
        dest = tmp_path / "out"
        dest.mkdir()
        data = _zip_bytes({"/etc/passwd": "evil"})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with pytest.raises(ValueError, match="Zip Slip"):
                _safe_extract_zip(zf, dest)


# ---------------------------------------------------------------------------
# _find_plugin_dir
# ---------------------------------------------------------------------------


class TestFindPluginDir:
    def test_plugin_json_at_base(self, tmp_path):
        (tmp_path / "plugin.json").write_text("{}", encoding="utf-8")
        assert _find_plugin_dir(tmp_path) == tmp_path

    def test_plugin_json_in_single_subdir(self, tmp_path):
        inner = tmp_path / "my-plugin"
        inner.mkdir()
        (inner / "plugin.json").write_text("{}", encoding="utf-8")
        assert _find_plugin_dir(tmp_path) == inner

    def test_no_plugin_json_raises(self, tmp_path):
        (tmp_path / "other.txt").write_text("x", encoding="utf-8")
        with pytest.raises(ValueError):
            _find_plugin_dir(tmp_path)


# ---------------------------------------------------------------------------
# _list_plugins_from_disk
# ---------------------------------------------------------------------------


def _write_plugin(plugin_dir: Path, manifest: dict):
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


class TestListPluginsFromDisk:
    def test_missing_plugins_dir_returns_empty(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "qwenpaw.config.utils.get_plugins_dir",
            lambda: tmp_path / "nonexistent",
        )
        assert _list_plugins_from_disk() == []

    def test_lists_valid_plugins(self, tmp_path, monkeypatch):
        plugins_dir = tmp_path / "plugins"
        monkeypatch.setattr(
            "qwenpaw.config.utils.get_plugins_dir",
            lambda: plugins_dir,
        )
        _write_plugin(
            plugins_dir / "my-plugin",
            {
                "id": "my-plugin",
                "name": "My Plugin",
                "version": "1.2.3",
                "description": "desc",
                "author": "me",
            },
        )
        result = _list_plugins_from_disk()
        assert len(result) == 1
        entry = result[0]
        assert entry["id"] == "my-plugin"
        assert entry["version"] == "1.2.3"
        assert entry["enabled"] is True
        assert entry["loaded"] is False

    def test_skips_disabled_and_hidden_dirs(self, tmp_path, monkeypatch):
        plugins_dir = tmp_path / "plugins"
        monkeypatch.setattr(
            "qwenpaw.config.utils.get_plugins_dir",
            lambda: plugins_dir,
        )
        _write_plugin(plugins_dir / "good", {"id": "good", "version": "1.0"})
        _write_plugin(
            plugins_dir / "off.disabled",
            {"id": "off", "version": "1.0"},
        )
        _write_plugin(
            plugins_dir / ".hidden",
            {"id": "hidden", "version": "1.0"},
        )
        result = _list_plugins_from_disk()
        assert [entry["id"] for entry in result] == ["good"]

    def test_skips_dir_without_manifest(self, tmp_path, monkeypatch):
        plugins_dir = tmp_path / "plugins"
        monkeypatch.setattr(
            "qwenpaw.config.utils.get_plugins_dir",
            lambda: plugins_dir,
        )
        (plugins_dir / "no-manifest").mkdir(parents=True)
        assert _list_plugins_from_disk() == []

    def test_malformed_manifest_skipped(self, tmp_path, monkeypatch):
        plugins_dir = tmp_path / "plugins"
        monkeypatch.setattr(
            "qwenpaw.config.utils.get_plugins_dir",
            lambda: plugins_dir,
        )
        bad = plugins_dir / "bad"
        bad.mkdir(parents=True)
        (bad / "plugin.json").write_text("{not json", encoding="utf-8")
        assert _list_plugins_from_disk() == []

    def test_non_dir_entries_ignored(self, tmp_path, monkeypatch):
        plugins_dir = tmp_path / "plugins"
        monkeypatch.setattr(
            "qwenpaw.config.utils.get_plugins_dir",
            lambda: plugins_dir,
        )
        plugins_dir.mkdir()
        (plugins_dir / "stray.txt").write_text("x", encoding="utf-8")
        assert _list_plugins_from_disk() == []


# ---------------------------------------------------------------------------
# serve_plugin_ui_file (via TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture
def ui_client(tmp_path, monkeypatch):
    """Client with no plugin loader (disk fallback path)."""
    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "ui-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"id": "ui-plugin"}),
        encoding="utf-8",
    )
    (plugin_dir / "ui").mkdir()
    (plugin_dir / "ui" / "app.js").write_text("console.log(1)")
    (plugin_dir / "ui" / "style.css").write_text("body{}")
    (plugin_dir / "ui" / "chunk-abcdefgh.js").write_text("// hashed")

    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: plugins_dir,
    )
    app = FastAPI()
    app.state.plugin_loader = None  # force disk fallback
    app.include_router(plugins_router, prefix="/api")
    return TestClient(app)


class TestServePluginUiFile:
    def test_serves_js_with_javascript_type(self, ui_client):
        response = ui_client.get(
            "/api/plugins/ui-plugin/files/ui/app.js",
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/javascript",
        )
        assert response.headers["cache-control"] == "no-cache"

    def test_hashed_asset_gets_immutable_cache(self, ui_client):
        response = ui_client.get(
            "/api/plugins/ui-plugin/files/ui/chunk-abcdefgh.js",
        )
        assert response.status_code == 200
        assert "immutable" in response.headers["cache-control"]

    def test_serves_css(self, ui_client):
        response = ui_client.get(
            "/api/plugins/ui-plugin/files/ui/style.css",
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/css")

    def test_missing_plugin_returns_404(self, ui_client):
        response = ui_client.get("/api/plugins/ghost/files/ui/app.js")
        assert response.status_code == 404

    def test_path_traversal_denied(self, ui_client, tmp_path, monkeypatch):
        """Call the handler directly: the HTTP layer normalizes '..'
        segments before routing, so traversal is probed at the function."""
        import asyncio
        from types import SimpleNamespace

        from qwenpaw.app.routers.plugins import serve_plugin_ui_file

        plugins_dir = tmp_path / "plugins"
        monkeypatch.setattr(
            "qwenpaw.config.utils.get_plugins_dir",
            lambda: plugins_dir,
        )
        request = SimpleNamespace(app=ui_client.app)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                serve_plugin_ui_file(
                    "ui-plugin",
                    "../../other.txt",
                    request,
                ),
            )
        assert exc_info.value.status_code in (403, 404)

    def test_missing_file_returns_404(self, ui_client):
        response = ui_client.get(
            "/api/plugins/ui-plugin/files/ui/ghost.js",
        )
        assert response.status_code == 404

    def test_loader_mode_unknown_plugin_404(self, tmp_path):
        from types import SimpleNamespace

        app = FastAPI()
        loader = SimpleNamespace()
        loader.get_loaded_plugin = lambda plugin_id: None
        app.state.plugin_loader = loader
        app.include_router(plugins_router, prefix="/api")
        client = TestClient(app)
        response = client.get("/api/plugins/ghost/files/ui/app.js")
        assert response.status_code == 404

# -*- coding: utf-8 -*-
"""Unit tests for cli/plugin_commands.py.

All network (HTTPX/urllib), subprocess (pip/uv), filesystem (plugins dir) and
config-system collaborators are monkeypatched at their source modules, so
every code path runs in-process against temporary directories. The Click
commands are driven through ``CliRunner`` against the ``plugin`` group.
"""
# pylint: disable=protected-access,unnecessary-lambda,unused-argument,unused-variable  # noqa: E501
from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path
from functools import partial

import httpx
import pytest
from click.testing import CliRunner

import qwenpaw.cli.plugin_commands as pc
import qwenpaw.config.utils as config_utils


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _http_error(payload: bytes | None = None) -> httpx.Response:
    body = payload if payload is not None else b'{"detail":"boom"}'
    return httpx.Response(500, content=body)


def _patch_transport(monkeypatch, handler):
    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(handler)),
    )


def _patch_plugins_dir(monkeypatch, tmp_path: Path) -> Path:
    pdir = tmp_path / "plugins"
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(config_utils, "WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(config_utils, "get_plugins_dir", lambda: pdir)
    return pdir


def _write_plugin(
    root: Path,
    pid: str = "demo",
    name: str = "Demo Plugin",
    extra: dict | None = None,
) -> Path:
    """Create a plugin directory with a minimal valid plugin.json."""
    manifest = {
        "id": pid,
        "name": name,
        "version": "1.0.0",
        "description": "demo plugin",
    }
    if extra:
        manifest.update(extra)
    (root / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (root / "backend.py").write_text(
        "class Plugin:\n    pass\n",
        encoding="utf-8",
    )
    return root


# ---------------------------------------------------------------------------
# _get_api_base
# ---------------------------------------------------------------------------


class TestGetApiBase:
    def test_returns_none_when_no_last_api(self, monkeypatch):
        monkeypatch.setattr(config_utils, "read_last_api", lambda: None)
        assert pc._get_api_base() is None

    def test_builds_url_from_last_api(self, monkeypatch):
        monkeypatch.setattr(
            config_utils,
            "read_last_api",
            lambda: ("127.0.0.1", 9001),
        )
        assert pc._get_api_base() == "http://127.0.0.1:9001/api"


# ---------------------------------------------------------------------------
# _api_install_plugin / _api_upload_plugin / _api_uninstall_plugin
# ---------------------------------------------------------------------------


def _patch_base(monkeypatch, base="http://h:1/api"):
    monkeypatch.setattr(pc, "_get_api_base", lambda: base)


class TestApiInstallPlugin:
    def test_no_api_base_returns_false(self, monkeypatch):
        monkeypatch.setattr(pc, "_get_api_base", lambda: None)
        assert pc._api_install_plugin("/some/dir") is False

    def test_success_echoes_and_returns_true(self, monkeypatch):
        _patch_base(monkeypatch)
        captured = {}

        def respond(req, timeout=None):
            captured["url"] = str(req.url)
            captured["body"] = req.content
            return _response({"name": "demo"})

        _patch_transport(
            monkeypatch,
            respond,
        )
        assert pc._api_install_plugin("https://x/p.zip", force=True) is True
        assert captured["url"].endswith("/plugins/install")
        assert json.loads(captured["body"]) == {
            "source": "https://x/p.zip",
            "force": True,
        }

    def test_http_error_with_json_detail(self, monkeypatch, capsys):
        _patch_base(monkeypatch)
        _patch_transport(
            monkeypatch,
            lambda req, timeout=None: _http_error(),
        )
        assert pc._api_install_plugin("src") is False
        assert "boom" in capsys.readouterr().err

    def test_http_error_with_non_json_body(self, monkeypatch, capsys):
        _patch_base(monkeypatch)
        _patch_transport(
            monkeypatch,
            lambda req, timeout=None: _http_error(b"not json"),
        )
        assert pc._api_install_plugin("src") is False
        assert "API install failed" in capsys.readouterr().err

    def test_generic_exception(self, monkeypatch, capsys):
        _patch_base(monkeypatch)

        def boom(req, timeout=None):
            raise OSError("net down")

        _patch_transport(monkeypatch, boom)
        assert pc._api_install_plugin("src") is False
        assert "net down" in capsys.readouterr().err


class TestApiUploadPlugin:
    def test_no_api_base(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc, "_get_api_base", lambda: None)
        z = tmp_path / "p.zip"
        z.write_bytes(b"")
        assert pc._api_upload_plugin(z) is False

    def test_success_builds_multipart_body(self, monkeypatch, tmp_path):
        _patch_base(monkeypatch)
        z = tmp_path / "p.zip"
        z.write_bytes(b"ZIPBYTES")
        captured = {}

        def respond(req, timeout=None):
            captured["url"] = str(req.url)
            captured["body"] = req.content
            captured["ctype"] = req.headers["Content-Type"]
            return _response({"name": "p"})

        _patch_transport(monkeypatch, respond)
        assert pc._api_upload_plugin(z, force=True) is True
        assert "force=true" in captured["url"]
        assert b"ZIPBYTES" in captured["body"]
        # body starts with "--" + boundary
        assert captured["body"].startswith(b"------QwenPawPluginUpload")
        assert captured["body"].endswith(b"--QwenPawPluginUpload--\r\n")
        assert "multipart/form-data" in captured["ctype"]

    def test_http_error(self, monkeypatch, tmp_path, capsys):
        _patch_base(monkeypatch)
        z = tmp_path / "p.zip"
        z.write_bytes(b"x")
        _patch_transport(
            monkeypatch,
            lambda req, timeout=None: _http_error(),
        )
        assert pc._api_upload_plugin(z) is False
        assert "boom" in capsys.readouterr().err

    def test_generic_exception(self, monkeypatch, tmp_path, capsys):
        _patch_base(monkeypatch)
        z = tmp_path / "p.zip"
        z.write_bytes(b"x")

        def boom(req, timeout=None):
            raise ConnectionError("down")

        _patch_transport(monkeypatch, boom)
        assert pc._api_upload_plugin(z) is False
        assert "down" in capsys.readouterr().err

    def test_http_error_with_non_json_body(
        self,
        monkeypatch,
        tmp_path,
        capsys,
    ):
        _patch_base(monkeypatch)
        z = tmp_path / "p.zip"
        z.write_bytes(b"x")
        _patch_transport(
            monkeypatch,
            lambda req, timeout=None: _http_error(b"garbage"),
        )
        assert pc._api_upload_plugin(z) is False
        assert "API upload failed" in capsys.readouterr().err


class TestApiUninstallPlugin:
    def test_no_api_base(self, monkeypatch):
        monkeypatch.setattr(pc, "_get_api_base", lambda: None)
        assert pc._api_uninstall_plugin("pid") is False

    def test_success_prints_message(self, monkeypatch):
        _patch_base(monkeypatch)
        captured = {}

        def respond(req, timeout=None):
            captured["method"] = req.method
            return _response({"message": "bye"})

        _patch_transport(monkeypatch, respond)
        assert pc._api_uninstall_plugin("pid") is True
        assert captured["method"] == "DELETE"

    def test_http_error(self, monkeypatch, capsys):
        _patch_base(monkeypatch)
        _patch_transport(
            monkeypatch,
            lambda req, timeout=None: _http_error(),
        )
        assert pc._api_uninstall_plugin("pid") is False
        assert "API uninstall failed" in capsys.readouterr().err

    def test_generic_exception(self, monkeypatch, capsys):
        _patch_base(monkeypatch)

        def boom(req, timeout=None):
            raise RuntimeError("x")

        _patch_transport(monkeypatch, boom)
        assert pc._api_uninstall_plugin("pid") is False
        assert "API request failed" in capsys.readouterr().err

    def test_http_error_with_non_json_body(self, monkeypatch, capsys):
        _patch_base(monkeypatch)
        _patch_transport(
            monkeypatch,
            lambda req, timeout=None: _http_error(b"garbage"),
        )
        assert pc._api_uninstall_plugin("pid") is False
        assert "API uninstall failed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# _is_running / _safe_extract_zip
# ---------------------------------------------------------------------------


class TestIsRunning:
    def test_delegates_to_config_utils(self, monkeypatch):
        monkeypatch.setattr(config_utils, "is_qwenpaw_running", lambda: True)
        assert pc._is_running() is True
        monkeypatch.setattr(config_utils, "is_qwenpaw_running", lambda: False)
        assert pc._is_running() is False


class TestSafeExtractZip:
    def _zip_with(self, tmp_path, names: list[str]) -> zipfile.ZipFile:
        zpath = tmp_path / "a.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for n in names:
                zf.writestr(n, "data")
        return zipfile.ZipFile(zpath)

    def test_safe_archive_extracts(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        zf = self._zip_with(tmp_path, ["plugin.json", "sub/main.py"])
        pc._safe_extract_zip(zf, out)
        zf.close()
        assert (out / "plugin.json").is_file()
        assert (out / "sub" / "main.py").is_file()

    def test_zip_slip_raises(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        zf = self._zip_with(tmp_path, ["../evil.txt"])
        with pytest.raises(ValueError, match="Zip Slip"):
            pc._safe_extract_zip(zf, out)
        zf.close()
        assert not (tmp_path / "evil.txt").exists()


# ---------------------------------------------------------------------------
# _download_plugin_from_url
# ---------------------------------------------------------------------------


def _make_zip_bytes(root_name: str | None, files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            full = f"{root_name}/{name}" if root_name else name
            zf.writestr(full, content)
    return buf.getvalue()


class TestDownloadPluginFromUrl:
    def _patch_retrieve(self, monkeypatch, data: bytes):
        def fake_retrieve(url, dest):
            Path(dest).write_bytes(data)
            return dest, {}

        monkeypatch.setattr(pc.urllib.request, "urlretrieve", fake_retrieve)

    def test_single_root_dir(self, monkeypatch, capsys):
        self._patch_retrieve(
            monkeypatch,
            _make_zip_bytes("myplugin", {"plugin.json": "{}"}),
        )
        plug, temp = pc._download_plugin_from_url("http://x/p.zip")
        assert plug.name == "myplugin"
        assert (plug / "plugin.json").is_file()
        pc.shutil.rmtree(temp)
        assert "Downloaded and extracted" in capsys.readouterr().out

    def test_root_level_manifest(self, monkeypatch):
        self._patch_retrieve(
            monkeypatch,
            _make_zip_bytes(None, {"plugin.json": "{}", "a.txt": "x"}),
        )
        plug, temp = pc._download_plugin_from_url("http://x/p.zip")
        assert plug == temp
        pc.shutil.rmtree(temp)

    def test_invalid_structure_raises(self, monkeypatch):
        self._patch_retrieve(
            monkeypatch,
            _make_zip_bytes(None, {"readme.txt": "x"}),
        )
        with pytest.raises(ValueError, match="Invalid plugin archive"):
            pc._download_plugin_from_url("http://x/p.zip")


# ---------------------------------------------------------------------------
# CLI: install (hot path while running)
# ---------------------------------------------------------------------------


class TestInstallCommandHotPath:
    def test_url_delegates_to_api_install(self, monkeypatch):
        monkeypatch.setattr(pc, "_is_running", lambda: True)
        seen = {}
        monkeypatch.setattr(
            pc,
            "_api_install_plugin",
            lambda source, force=False: seen.setdefault(
                "call",
                (source, force),
            )
            or True,
        )
        res = CliRunner().invoke(
            pc.plugin,
            ["install", "https://x/p.zip", "--force"],
        )
        assert res.exit_code == 0
        assert seen["call"] == ("https://x/p.zip", True)
        assert "hot-install" in res.output

    def test_local_zip_uploads(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc, "_is_running", lambda: True)
        z = tmp_path / "p.zip"
        z.write_bytes(b"x")
        seen = {}
        monkeypatch.setattr(
            pc,
            "_api_upload_plugin",
            lambda zp, force=False: seen.setdefault("zp", zp) or True,
        )
        res = CliRunner().invoke(pc.plugin, ["install", str(z)])
        assert res.exit_code == 0
        assert seen["zp"] == z

    def test_local_dir_installs(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc, "_is_running", lambda: True)
        d = tmp_path / "plug"
        d.mkdir()
        monkeypatch.setattr(
            pc,
            "_api_install_plugin",
            lambda source, force=False: True,
        )
        res = CliRunner().invoke(pc.plugin, ["install", str(d)])
        assert res.exit_code == 0

    def test_missing_path_errors(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc, "_is_running", lambda: True)
        res = CliRunner().invoke(
            pc.plugin,
            ["install", str(tmp_path / "nope")],
        )
        assert res.exit_code == 0
        assert "Path not found" in res.output

    def test_unsupported_file_type(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc, "_is_running", lambda: True)
        f = tmp_path / "p.tar.gz"
        f.write_bytes(b"x")
        res = CliRunner().invoke(pc.plugin, ["install", str(f)])
        assert res.exit_code == 0
        assert "directory or a .zip" in res.output


# ---------------------------------------------------------------------------
# CLI: install (offline path)
# ---------------------------------------------------------------------------


class TestInstallCommandOffline:
    def _offline(self, monkeypatch):
        monkeypatch.setattr(pc, "_is_running", lambda: False)

    def test_download_failure(self, monkeypatch, capsys):
        self._offline(monkeypatch)

        def boom(url):
            raise OSError("dns down")

        monkeypatch.setattr(pc, "_download_plugin_from_url", boom)
        res = CliRunner().invoke(
            pc.plugin,
            ["install", "https://x/p.zip"],
        )
        assert res.exit_code == 0
        assert "Failed to download" in res.output

    def test_missing_local_path(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        res = CliRunner().invoke(
            pc.plugin,
            ["install", str(tmp_path / "ghost")],
        )
        assert "Path not found" in res.output

    def test_missing_manifest(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        d = tmp_path / "src"
        d.mkdir()
        res = CliRunner().invoke(pc.plugin, ["install", str(d)])
        assert "plugin.json not found" in res.output

    def test_invalid_manifest_json(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        d = tmp_path / "src"
        d.mkdir()
        (d / "plugin.json").write_text("{bad")
        res = CliRunner().invoke(pc.plugin, ["install", str(d)])
        assert res.exit_code != 0
        assert "Failed to install plugin" in res.output

    def test_manifest_read_failure_generic(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        d = tmp_path / "src"
        d.mkdir()
        (d / "plugin.json").write_bytes(b"\xff\xfe\x00invalid")
        res = CliRunner().invoke(pc.plugin, ["install", str(d)])
        assert res.exit_code != 0
        assert "Failed to install plugin" in res.output

    def test_manifest_missing_fields(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        d = tmp_path / "src"
        d.mkdir()
        (d / "plugin.json").write_text(json.dumps({"id": "x"}))
        res = CliRunner().invoke(pc.plugin, ["install", str(d)])
        assert res.exit_code != 0
        assert "Field required" in res.output

    def test_already_exists_without_force(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        _write_plugin(src)
        (pdir / "demo").mkdir(parents=True)
        res = CliRunner().invoke(pc.plugin, ["install", str(src)])
        assert "already exists" in res.output

    def test_validation_failure_blocks_copy(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        _write_plugin(src, extra={"entry": {"backend": "backend.py"}})

        (src / "backend.py").write_text("def broken(\n")
        res = CliRunner().invoke(pc.plugin, ["install", str(src)])
        assert res.exit_code != 0
        assert "never closed" in res.output
        assert not (pdir / "demo").exists()

    def test_copy_failure(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        _patch_plugins_dir(monkeypatch, tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        _write_plugin(src)
        monkeypatch.setattr(pc, "_validate_plugin_module", lambda *a: None)

        def boom(s, t, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(pc.shutil, "copytree", boom)
        res = CliRunner().invoke(pc.plugin, ["install", str(src)])
        assert res.exit_code != 0
        assert "disk full" in res.output

    def test_url_install_temp_dir_cleanup_failure_swallowed(
        self,
        monkeypatch,
        tmp_path,
    ):
        self._offline(monkeypatch)
        _patch_plugins_dir(monkeypatch, tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        _write_plugin(src)
        temp = tmp_path / "tempdl"
        temp.mkdir()
        monkeypatch.setattr(
            pc,
            "_download_plugin_from_url",
            lambda url: (src, temp),
        )
        monkeypatch.setattr(pc, "_validate_plugin_module", lambda *a: None)
        real_rmtree = pc.shutil.rmtree

        def selective_rmtree(path, *a, **kw):
            if Path(path) == temp:
                raise OSError("locked")
            return real_rmtree(path, *a, **kw)

        monkeypatch.setattr(pc.shutil, "rmtree", selective_rmtree)
        res = CliRunner().invoke(
            pc.plugin,
            ["install", "https://x/p.zip"],
        )
        assert res.exit_code == 0
        assert "installed successfully" in res.output

    def test_force_reinstall_replaces_existing(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        _write_plugin(src)
        old = pdir / "demo"
        old.mkdir(parents=True)
        _write_plugin(old)
        (old / "stale.txt").write_text("old")
        monkeypatch.setattr(pc, "_validate_plugin_module", lambda *a: None)
        res = CliRunner().invoke(
            pc.plugin,
            ["install", str(src), "--force"],
        )
        assert res.exit_code == 0
        assert not (old / "stale.txt").exists()
        assert (old / "plugin.json").is_file()


# ---------------------------------------------------------------------------
# CLI: list / info
# ---------------------------------------------------------------------------


class TestListCommand:
    def test_no_plugins_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            config_utils,
            "get_plugins_dir",
            lambda: tmp_path / "missing",
        )
        res = CliRunner().invoke(pc.plugin, ["list"])
        assert res.exit_code == 0
        assert "No plugins installed" in res.output

    def test_empty_dir(self, monkeypatch, tmp_path):
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        pdir.mkdir()
        res = CliRunner().invoke(pc.plugin, ["list"])
        assert "No plugins installed" in res.output

    def test_lists_manifests_skips_files_and_bad_jsons(
        self,
        monkeypatch,
        tmp_path,
    ):
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        pdir.mkdir()
        good = pdir / "good"
        good.mkdir()
        _write_plugin(good, pid="good", name="Good")
        bad = pdir / "bad"
        bad.mkdir()
        (bad / "plugin.json").write_text("{oops")
        (pdir / "stray.txt").write_text("x")
        res = CliRunner().invoke(pc.plugin, ["list"])
        assert res.exit_code == 0
        assert "Good" in res.output
        assert "ID: good" in res.output
        assert "Description: demo plugin" in res.output

    def test_dirs_without_manifest_ignored(self, monkeypatch, tmp_path):
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        (pdir / "nomanifest").mkdir(parents=True)
        res = CliRunner().invoke(pc.plugin, ["list"])
        assert "No plugins installed" in res.output


class TestInfoCommand:
    def test_plugin_not_found(self, monkeypatch, tmp_path):
        _patch_plugins_dir(monkeypatch, tmp_path)
        res = CliRunner().invoke(pc.plugin, ["info", "nope"])
        assert res.exit_code == 0
        assert "not found" in res.output

    def test_missing_manifest(self, monkeypatch, tmp_path):
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        (pdir / "pid").mkdir(parents=True)
        res = CliRunner().invoke(pc.plugin, ["info", "pid"])
        assert "plugin.json not found" in res.output

    def test_broken_manifest(self, monkeypatch, tmp_path):
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        d = pdir / "pid"
        d.mkdir(parents=True)
        (d / "plugin.json").write_text("nope{")
        res = CliRunner().invoke(pc.plugin, ["info", "pid"])
        assert "Failed to read" in res.output

    def test_full_info_output(self, monkeypatch, tmp_path):
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        d = pdir / "demo"
        d.mkdir(parents=True)
        manifest = {
            "id": "demo",
            "name": "Demo",
            "version": "2.0",
            "author": "tester",
            "description": "desc",
            "entry": {"backend": "b.py", "frontend": "f/index.js"},
            "dependencies": ["httpx"],
            "meta": {
                "api_key_url": "https://keys.example.com",
                "api_key_hint": "sk-...",
            },
        }
        (d / "plugin.json").write_text(json.dumps(manifest))
        res = CliRunner().invoke(pc.plugin, ["info", "demo"])
        assert res.exit_code == 0
        for needle in (
            "Demo (v2.0)",
            "ID: demo",
            "Author: tester",
            "Backend Entry: b.py",
            "Frontend Entry: f/index.js",
            "- httpx",
            "API Key",
            "sk-...",
            "Location:",
        ):
            assert needle in res.output


# ---------------------------------------------------------------------------
# _resolve_plugin_id / uninstall / validate
# ---------------------------------------------------------------------------


class TestResolvePluginId:
    def test_plain_id_passthrough(self):
        assert pc._resolve_plugin_id("gpt-image2-tool") == "gpt-image2-tool"

    def test_directory_with_manifest(self, tmp_path):
        d = tmp_path / "plug"
        d.mkdir()
        (d / "plugin.json").write_text(json.dumps({"id": "from-dir"}))
        assert pc._resolve_plugin_id(str(d)) == "from-dir"

    def test_directory_with_broken_manifest(self, tmp_path):
        d = tmp_path / "plug"
        d.mkdir()
        (d / "plugin.json").write_text("{bad")
        assert pc._resolve_plugin_id(str(d)) is None


class TestUninstallCommand:
    def test_unresolvable_id(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc, "_resolve_plugin_id", lambda p: None)
        res = CliRunner().invoke(pc.plugin, ["uninstall", "x"])
        assert "Could not determine plugin ID" in res.output

    def test_hot_path_cancel(self, monkeypatch):
        monkeypatch.setattr(pc, "_resolve_plugin_id", lambda p: "pid")
        monkeypatch.setattr(pc, "_is_running", lambda: True)
        res = CliRunner().invoke(pc.plugin, ["uninstall", "pid"], input="n\n")
        assert res.exit_code == 0
        assert "Cancelled" in res.output

    def test_hot_path_confirm_calls_api(self, monkeypatch):
        monkeypatch.setattr(pc, "_resolve_plugin_id", lambda p: "pid")
        monkeypatch.setattr(pc, "_is_running", lambda: True)
        seen = []
        monkeypatch.setattr(
            pc,
            "_api_uninstall_plugin",
            lambda pid: seen.append(pid) or True,
        )
        res = CliRunner().invoke(pc.plugin, ["uninstall", "pid"], input="y\n")
        assert res.exit_code == 0
        assert seen == ["pid"]

    def test_offline_not_found(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc, "_is_running", lambda: False)
        _patch_plugins_dir(monkeypatch, tmp_path)
        res = CliRunner().invoke(pc.plugin, ["uninstall", "ghost"])
        assert "not found" in res.output

    def test_offline_cancel_keeps_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc, "_is_running", lambda: False)
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        d = pdir / "demo"
        d.mkdir(parents=True)
        _write_plugin(d)
        res = CliRunner().invoke(
            pc.plugin,
            ["uninstall", "demo"],
            input="n\n",
        )
        assert "Cancelled" in res.output
        assert d.exists()

    def test_offline_uninstall_broken_manifest_still_removes(
        self,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setattr(pc, "_is_running", lambda: False)
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        d = pdir / "demo"
        d.mkdir(parents=True)
        (d / "plugin.json").write_text("{broken")
        res = CliRunner().invoke(
            pc.plugin,
            ["uninstall", "demo"],
            input="y\n",
        )
        assert res.exit_code == 0
        assert not d.exists()

    def test_rmtree_failure_reported(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc, "_is_running", lambda: False)
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        d = pdir / "demo"
        d.mkdir(parents=True)
        _write_plugin(d)

        def boom(path, **kw):
            raise OSError("locked")

        monkeypatch.setattr(pc.shutil, "rmtree", boom)
        res = CliRunner().invoke(
            pc.plugin,
            ["uninstall", "demo"],
            input="y\n",
        )
        assert "Failed to uninstall" in res.output


class TestValidateCommand:
    def test_path_not_found(self, tmp_path):
        res = CliRunner().invoke(
            pc.plugin,
            ["validate", str(tmp_path / "nope")],
        )
        assert "Path not found" in res.output

    def test_missing_manifest(self, tmp_path):
        d = tmp_path / "p"
        d.mkdir()
        res = CliRunner().invoke(pc.plugin, ["validate", str(d)])
        assert "plugin.json not found" in res.output

    def test_invalid_json(self, tmp_path):
        d = tmp_path / "p"
        d.mkdir()
        (d / "plugin.json").write_text("{x")
        res = CliRunner().invoke(pc.plugin, ["validate", str(d)])
        assert "Invalid JSON" in res.output

    def test_missing_required_field(self, tmp_path):
        d = tmp_path / "p"
        d.mkdir()
        (d / "plugin.json").write_text(json.dumps({"id": "a", "name": "b"}))
        res = CliRunner().invoke(pc.plugin, ["validate", str(d)])
        assert "Missing required field: version" in res.output

    def test_backend_entry_validation_failure(self, monkeypatch, tmp_path):
        d = tmp_path / "p"
        d.mkdir()
        (d / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "a",
                    "name": "b",
                    "version": "1",
                    "entry": {"backend": "backend.py"},
                },
            ),
        )

        def bad(pid, path, entry):
            raise FileNotFoundError("missing")

        monkeypatch.setattr(pc, "_validate_plugin_module", bad)
        res = CliRunner().invoke(pc.plugin, ["validate", str(d)])
        assert "Validation failed" in res.output

    def test_frontend_entry_missing_warns(self, tmp_path):
        d = tmp_path / "p"
        d.mkdir()
        (d / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "a",
                    "name": "b",
                    "version": "1",
                    "entry": {"frontend": "dist/index.js"},
                },
            ),
        )
        res = CliRunner().invoke(pc.plugin, ["validate", str(d)])
        assert res.exit_code == 0
        assert "validation passed" in res.output
        assert "Frontend entry not found" in res.output

    def test_success(self, tmp_path):
        d = tmp_path / "p"
        d.mkdir()
        (d / "plugin.json").write_text(
            json.dumps({"id": "a", "name": "b", "version": "1"}),
        )
        res = CliRunner().invoke(pc.plugin, ["validate", str(d)])
        assert res.exit_code == 0
        assert "validation passed" in res.output
        assert "ID: a" in res.output


@pytest.fixture(name="offline_environment")
def _offline_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("QWENPAW_RUNTIME_ID", raising=False)
    monkeypatch.delenv("QWENPAW_RUNTIME_PROVISIONER", raising=False)
    monkeypatch.setattr(pc, "_is_running", lambda: False)
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    return _patch_plugins_dir(monkeypatch, tmp_path)


def test_offline_force_dependency_failure_preserves_old(
    monkeypatch,
    tmp_path,
    offline_environment,
):
    old = offline_environment / "demo"
    old.mkdir(parents=True)
    _write_plugin(old)
    (old / "user.txt").write_text("keep")
    source = tmp_path / "source"
    source.mkdir()
    _write_plugin(source, extra={"version": "2.0.0"})
    (source / "requirements.txt").write_text("qwenpaw-test-missing==1\n")
    calls = []

    def fail_install(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args[0], 1, "", "deps failed")

    from qwenpaw.plugins.loader import PluginLoader

    monkeypatch.setattr(
        PluginLoader,
        "_run_subprocess_with_streaming_log",
        staticmethod(fail_install),
    )
    result = CliRunner().invoke(
        pc.plugin,
        ["install", str(source), "--force"],
    )
    assert calls
    assert "installed successfully" not in result.output
    assert json.loads((old / "plugin.json").read_text())["version"] == "1.0.0"
    assert (old / "user.txt").read_text() == "keep"


def test_offline_install_defers_import_registration_and_startup(
    tmp_path,
    offline_environment,
):
    source = tmp_path / "source"
    source.mkdir()
    _write_plugin(source, extra={"entry": {"backend": "backend.py"}})
    marker = tmp_path / "imported"
    (source / "backend.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported')\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        f"        Path({str(marker)!r}).write_text('registered')\n"
        "    async def startup(self, api):\n"
        f"        Path({str(marker)!r}).write_text('started')\n"
        "plugin = Plugin()\n",
    )
    result = CliRunner().invoke(pc.plugin, ["install", str(source)])
    assert result.exit_code == 0, result.output
    assert "installed successfully" in result.output
    assert (offline_environment / "demo" / "plugin.json").is_file()
    assert not marker.exists()


@pytest.mark.parametrize("owned", [True, False])
def test_offline_uninstall_respects_inventory_ownership(
    tmp_path,
    offline_environment,
    owned,
):
    from qwenpaw.plugins.provision import inventory_path, save_inventory

    root = offline_environment / "demo"
    root.mkdir(parents=True)
    _write_plugin(root)
    dest = tmp_path / "data"
    dest.mkdir()
    (dest / "user.txt").write_text("keep")
    save_inventory(
        "demo",
        {
            "locations": {str(dest): {"owned": owned}},
            "provisions": [],
        },
    )
    result = CliRunner().invoke(
        pc.plugin,
        ["uninstall", "demo"],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert "uninstalled successfully" in result.output
    assert dest.exists() is not owned
    if not owned:
        assert (dest / "user.txt").read_text() == "keep"
    assert not inventory_path("demo").exists()
    assert not root.exists()


def test_offline_uninstall_config_failure_retains_cleanup_for_retry(
    monkeypatch,
    tmp_path,
    offline_environment,
):
    from types import SimpleNamespace
    from qwenpaw.plugins.provision import inventory_path, record_tool_factory
    import qwenpaw.config.config as cc

    root = offline_environment / "demo"
    root.mkdir(parents=True)
    _write_plugin(root)
    record_tool_factory("demo", "send_message", {"enabled": True})
    config = cc.Config()
    monkeypatch.setattr(config_utils, "load_config", lambda *args: config)
    monkeypatch.setattr(
        cc,
        "load_agent_config",
        lambda agent: SimpleNamespace(
            tools=SimpleNamespace(builtin_tools={"send_message": {}}),
        ),
    )

    def fail_save(*args):
        raise PermissionError("agent config is read-only")

    monkeypatch.setattr(cc, "save_agent_config", fail_save)
    result = CliRunner().invoke(
        pc.plugin,
        ["uninstall", "demo"],
        input="y\n",
    )
    assert result.exit_code != 0
    assert "agent config is read-only" in result.output
    assert "uninstalled successfully" not in result.output
    assert root.is_dir()
    assert inventory_path("demo").is_file()
    monkeypatch.setattr(cc, "save_agent_config", lambda *args: None)
    result = CliRunner().invoke(
        pc.plugin,
        ["uninstall", "demo"],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert "uninstalled successfully" in result.output
    assert not root.exists()
    assert not inventory_path("demo").exists()


@pytest.mark.parametrize("failure_stage", ["commit", "cleanup"])
def test_offline_force_install_respects_durable_commit(
    monkeypatch,
    tmp_path,
    offline_environment,
    failure_stage,
):
    from qwenpaw.plugins import loader, updates

    old = offline_environment / "demo"
    old.mkdir(parents=True)
    _write_plugin(old)
    (old / "user.txt").write_text("old data")
    source = tmp_path / "source"
    source.mkdir()
    _write_plugin(source, extra={"version": "2.0.0"})

    def fail(*args):
        raise PermissionError(f"{failure_stage} blocked")

    if failure_stage == "commit":
        monkeypatch.setattr(updates, "mark_update_committed", fail)
    else:
        monkeypatch.setattr(loader, "_remove_dir", fail)
    result = CliRunner().invoke(
        pc.plugin,
        ["install", str(source), "--force"],
    )
    assert result.exit_code != 0
    assert f"{failure_stage} blocked" in result.output
    assert "installed successfully" not in result.output
    version = json.loads((old / "plugin.json").read_text())["version"]
    marker = updates.marker_path("demo")
    if failure_stage == "commit":
        assert version == "1.0.0"
        assert (old / "user.txt").read_text() == "old data"
        assert not marker.exists()
    else:
        assert version == "2.0.0"
        saved = json.loads(marker.read_text())
        assert saved["status"] == "committed"
        backup = Path(saved["backup_path"])
        assert (backup / "user.txt").read_text() == "old data"

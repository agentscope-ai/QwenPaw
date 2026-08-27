# -*- coding: utf-8 -*-
"""Unit tests for cli/plugin_commands.py.

All network (urllib), subprocess (pip/uv), filesystem (plugins dir) and
config-system collaborators are monkeypatched at their source modules, so
every code path runs in-process against temporary directories. The Click
commands are driven through ``CliRunner`` against the ``plugin`` group.
"""
# pylint: disable=protected-access,unnecessary-lambda,unused-argument,unused-variable  # noqa: E501
from __future__ import annotations

import io
import json
import subprocess
import urllib.error
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

import qwenpaw.cli.plugin_commands as pc
import qwenpaw.config.utils as config_utils


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _FakeResp(io.BytesIO):
    """urlopen() result supporting context-manager + read()."""

    def __init__(self, payload: dict):
        super().__init__(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _http_error(payload: bytes | None = None) -> urllib.error.HTTPError:
    body = (
        payload
        if payload is not None
        else json.dumps(
            {"detail": "boom"},
        ).encode()
    )
    return urllib.error.HTTPError(
        "http://x/api",
        500,
        "server error",
        {},  # type: ignore[arg-type]
        io.BytesIO(body),
    )


def _patch_plugins_dir(monkeypatch, tmp_path: Path) -> Path:
    pdir = tmp_path / "plugins"
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

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = req.data
            return _FakeResp({"name": "demo"})

        monkeypatch.setattr(
            pc.urllib.request,
            "urlopen",
            fake_urlopen,
        )
        assert pc._api_install_plugin("https://x/p.zip", force=True) is True
        assert captured["url"].endswith("/plugins/install")
        assert json.loads(captured["body"]) == {
            "source": "https://x/p.zip",
            "force": True,
        }

    def test_http_error_with_json_detail(self, monkeypatch, capsys):
        _patch_base(monkeypatch)
        monkeypatch.setattr(
            pc.urllib.request,
            "urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(
                _http_error(),
            ),
        )
        assert pc._api_install_plugin("src") is False
        assert "boom" in capsys.readouterr().err

    def test_http_error_with_non_json_body(self, monkeypatch, capsys):
        _patch_base(monkeypatch)
        monkeypatch.setattr(
            pc.urllib.request,
            "urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(
                _http_error(b"not json"),
            ),
        )
        assert pc._api_install_plugin("src") is False
        assert "API install failed" in capsys.readouterr().err

    def test_generic_exception(self, monkeypatch, capsys):
        _patch_base(monkeypatch)

        def boom(req, timeout=None):
            raise OSError("net down")

        monkeypatch.setattr(pc.urllib.request, "urlopen", boom)
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

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = req.data
            captured["ctype"] = req.get_header("Content-type")
            return _FakeResp({"name": "p"})

        monkeypatch.setattr(pc.urllib.request, "urlopen", fake_urlopen)
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
        monkeypatch.setattr(
            pc.urllib.request,
            "urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(_http_error()),
        )
        assert pc._api_upload_plugin(z) is False
        assert "boom" in capsys.readouterr().err

    def test_generic_exception(self, monkeypatch, tmp_path, capsys):
        _patch_base(monkeypatch)
        z = tmp_path / "p.zip"
        z.write_bytes(b"x")

        def boom(req, timeout=None):
            raise ConnectionError("down")

        monkeypatch.setattr(pc.urllib.request, "urlopen", boom)
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
        monkeypatch.setattr(
            pc.urllib.request,
            "urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(
                _http_error(b"garbage"),
            ),
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

        def fake_urlopen(req, timeout=None):
            captured["method"] = req.get_method()
            return _FakeResp({"message": "bye"})

        monkeypatch.setattr(pc.urllib.request, "urlopen", fake_urlopen)
        assert pc._api_uninstall_plugin("pid") is True
        assert captured["method"] == "DELETE"

    def test_http_error(self, monkeypatch, capsys):
        _patch_base(monkeypatch)
        monkeypatch.setattr(
            pc.urllib.request,
            "urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(_http_error()),
        )
        assert pc._api_uninstall_plugin("pid") is False
        assert "API uninstall failed" in capsys.readouterr().err

    def test_generic_exception(self, monkeypatch, capsys):
        _patch_base(monkeypatch)

        def boom(req, timeout=None):
            raise RuntimeError("x")

        monkeypatch.setattr(pc.urllib.request, "urlopen", boom)
        assert pc._api_uninstall_plugin("pid") is False
        assert "API request failed" in capsys.readouterr().err

    def test_http_error_with_non_json_body(self, monkeypatch, capsys):
        _patch_base(monkeypatch)
        monkeypatch.setattr(
            pc.urllib.request,
            "urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(
                _http_error(b"garbage"),
            ),
        )
        assert pc._api_uninstall_plugin("pid") is False
        assert "API uninstall failed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# _find_uv
# ---------------------------------------------------------------------------


class TestFindUv:
    def test_found_on_path(self, monkeypatch):
        monkeypatch.setattr(pc.shutil, "which", lambda name: "/usr/bin/uv")
        assert pc._find_uv() == "/usr/bin/uv"

    def test_found_in_local_bin(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc.shutil, "which", lambda name: None)
        uv = tmp_path / ".local" / "bin" / "uv"
        uv.parent.mkdir(parents=True)
        uv.write_text("")
        monkeypatch.setattr(
            pc.Path,
            "home",
            classmethod(lambda cls: tmp_path),
        )
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert pc._find_uv() == str(uv)

    def test_found_in_windows_appdata(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc.shutil, "which", lambda name: None)
        lad = tmp_path / "lad"
        uv = lad / "Programs" / "uv" / "uv.exe"
        uv.parent.mkdir(parents=True)
        uv.write_text("")
        monkeypatch.setattr(
            pc.Path,
            "home",
            classmethod(lambda cls: tmp_path / "nohome"),
        )
        monkeypatch.setenv("LOCALAPPDATA", str(lad))
        assert pc._find_uv() == str(uv)

    def test_not_found(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pc.shutil, "which", lambda name: None)
        monkeypatch.setattr(
            pc.Path,
            "home",
            classmethod(lambda cls: tmp_path / "nohome"),
        )
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert pc._find_uv() is None


# ---------------------------------------------------------------------------
# _install_requirements_cli
# ---------------------------------------------------------------------------


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestInstallRequirementsCli:
    def test_pip_success(self, monkeypatch, tmp_path, capsys):
        req = tmp_path / "requirements.txt"
        req.write_text("x==1\n")
        target = tmp_path / "plugin"
        target.mkdir()
        monkeypatch.setattr(
            pc.subprocess,
            "run",
            lambda cmd, **kw: _Completed(0),
        )
        assert pc._install_requirements_cli(req, target) is True
        assert "Dependencies installed" in capsys.readouterr().out
        assert target.exists()

    def test_pip_timeout_cleans_up(self, monkeypatch, tmp_path, capsys):
        req = tmp_path / "requirements.txt"
        req.write_text("")
        target = tmp_path / "plugin"
        target.mkdir()

        def boom(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 300)

        monkeypatch.setattr(pc.subprocess, "run", boom)
        assert pc._install_requirements_cli(req, target) is False
        assert not target.exists()
        assert "timed out" in capsys.readouterr().err

    def test_pip_hard_failure_cleans_up(self, monkeypatch, tmp_path, capsys):
        req = tmp_path / "requirements.txt"
        req.write_text("")
        target = tmp_path / "plugin"
        target.mkdir()
        monkeypatch.setattr(
            pc.subprocess,
            "run",
            lambda cmd, **kw: _Completed(1, stderr="nope"),
        )
        assert pc._install_requirements_cli(req, target) is False
        assert not target.exists()
        assert "nope" in capsys.readouterr().err

    def test_pip_missing_and_no_uv(self, monkeypatch, tmp_path, capsys):
        req = tmp_path / "requirements.txt"
        req.write_text("")
        target = tmp_path / "plugin"
        target.mkdir()
        monkeypatch.setattr(
            pc.subprocess,
            "run",
            lambda cmd, **kw: _Completed(1, stderr="No module named pip"),
        )
        monkeypatch.setattr(pc, "_find_uv", lambda: None)
        assert pc._install_requirements_cli(req, target) is False
        assert not target.exists()
        assert "uv was not found" in capsys.readouterr().err

    def test_pip_missing_then_uv_success(self, monkeypatch, tmp_path, capsys):
        req = tmp_path / "requirements.txt"
        req.write_text("")
        target = tmp_path / "plugin"
        target.mkdir()
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[1:3] == ["-m", "pip"]:
                return _Completed(1, stderr="No module named pip")
            return _Completed(0)

        monkeypatch.setattr(pc.subprocess, "run", fake_run)
        monkeypatch.setattr(pc, "_find_uv", lambda: "/usr/bin/uv")
        assert pc._install_requirements_cli(req, target) is True
        assert target.exists()
        assert calls[1][0] == "/usr/bin/uv"
        assert "(via uv)" in capsys.readouterr().out

    def test_pip_missing_then_uv_timeout(self, monkeypatch, tmp_path, capsys):
        req = tmp_path / "requirements.txt"
        req.write_text("")
        target = tmp_path / "plugin"
        target.mkdir()

        def fake_run(cmd, **kw):
            if cmd[1:3] == ["-m", "pip"]:
                return _Completed(1, stderr="No module named pip")
            raise subprocess.TimeoutExpired(cmd, 300)

        monkeypatch.setattr(pc.subprocess, "run", fake_run)
        monkeypatch.setattr(pc, "_find_uv", lambda: "/usr/bin/uv")
        assert pc._install_requirements_cli(req, target) is False
        assert not target.exists()
        assert "via uv" in capsys.readouterr().err

    def test_pip_missing_then_uv_failure(self, monkeypatch, tmp_path, capsys):
        req = tmp_path / "requirements.txt"
        req.write_text("")
        target = tmp_path / "plugin"
        target.mkdir()

        def fake_run(cmd, **kw):
            if cmd[1:3] == ["-m", "pip"]:
                return _Completed(1, stdout="No module named pip")
            return _Completed(2, stderr="uv broke")

        monkeypatch.setattr(pc.subprocess, "run", fake_run)
        monkeypatch.setattr(pc, "_find_uv", lambda: "/usr/bin/uv")
        assert pc._install_requirements_cli(req, target) is False
        assert not target.exists()
        assert "uv broke" in capsys.readouterr().err


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
# _sync_tool_plugin_to_agents / _remove_tool_plugin_from_agents
# ---------------------------------------------------------------------------


class _AgentConfig:
    def __init__(self, tools=None):
        self.tools = tools or _Tools()


class _Tools:
    def __init__(self):
        self.builtin_tools = {}


class TestSyncToolPluginToAgents:
    def test_non_tool_manifest_noop(self, capsys):
        pc._sync_tool_plugin_to_agents({"meta": {}})
        assert capsys.readouterr().out == ""

    def test_no_agents_found(self, monkeypatch, capsys):
        monkeypatch.setattr(config_utils, "load_config", lambda: _Cfg({}))
        pc._sync_tool_plugin_to_agents({"meta": {"tool_name": "t1"}})
        assert "No agents found" in capsys.readouterr().out

    def test_syncs_to_agents_missing_tool(self, monkeypatch, capsys):
        saved = {}

        monkeypatch.setattr(
            config_utils,
            "load_config",
            lambda: _Cfg({"a1": object(), "a2": object()}),
        )

        cfgs = {"a1": _AgentConfig(), "a2": _AgentConfig(_Tools())}
        cfgs["a2"].tools.builtin_tools["t1"] = object()

        import qwenpaw.config.config as cc

        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda aid: cfgs[aid],
        )

        def fake_save(aid, cfg):
            saved[aid] = cfg

        monkeypatch.setattr(cc, "save_agent_config", fake_save)
        pc._sync_tool_plugin_to_agents({"meta": {"tool_name": "t1"}})
        out = capsys.readouterr().out
        assert "Synced tool to 1 agent" in out
        assert list(saved) == ["a1"]
        assert "t1" in saved["a1"].tools.builtin_tools

    def test_all_agents_already_have_tool(self, monkeypatch, capsys):
        monkeypatch.setattr(
            config_utils,
            "load_config",
            lambda: _Cfg({"a1": object()}),
        )
        cfg = _AgentConfig()
        cfg.tools.builtin_tools["t1"] = object()
        import qwenpaw.config.config as cc

        monkeypatch.setattr(cc, "load_agent_config", lambda aid: cfg)
        pc._sync_tool_plugin_to_agents({"meta": {"tool_name": "t1"}})
        assert "already have this tool" in capsys.readouterr().out

    def test_load_failure_is_warned_not_raised(self, monkeypatch, capsys):
        monkeypatch.setattr(
            config_utils,
            "load_config",
            lambda: _Cfg({"a1": object()}),
        )
        import qwenpaw.config.config as cc

        def boom(aid):
            raise RuntimeError("bad json")

        monkeypatch.setattr(cc, "load_agent_config", boom)
        pc._sync_tool_plugin_to_agents({"meta": {"tool_name": "t1"}})
        out = capsys.readouterr().out
        assert "Synced tool to" not in out


class _Cfg:
    def __init__(self, profiles):
        self.agents = _Agents(profiles)


class _Agents:
    def __init__(self, profiles):
        self.profiles = profiles


class TestRemoveToolPluginFromAgents:
    def test_non_tool_manifest_noop(self, capsys):
        pc._remove_tool_plugin_from_agents({})
        assert capsys.readouterr().out == ""

    def test_no_agent_dirs(self, monkeypatch, capsys):
        monkeypatch.setattr(config_utils, "get_agent_dirs", lambda: [])
        pc._remove_tool_plugin_from_agents({"meta": {"tool_name": "t1"}})
        assert "No agents found" in capsys.readouterr().out

    def test_removes_from_agents(self, monkeypatch, tmp_path, capsys):
        d1 = tmp_path / "a1"
        d1.mkdir()
        (d1 / "agent.json").write_text("{}")
        d2 = tmp_path / "a2"  # no agent.json -> skipped
        d2.mkdir()
        monkeypatch.setattr(
            config_utils,
            "get_agent_dirs",
            lambda: [d1, d2],
        )
        cfg = _AgentConfig()
        cfg.tools.builtin_tools["t1"] = object()
        saved = []

        import qwenpaw.config.config as cc

        monkeypatch.setattr(cc, "load_agent_config", lambda p: cfg)
        monkeypatch.setattr(
            cc,
            "save_agent_config",
            lambda p, c: saved.append(p),
        )
        pc._remove_tool_plugin_from_agents({"meta": {"tool_name": "t1"}})
        out = capsys.readouterr().out
        assert "Removed tool from 1 agent" in out
        assert "t1" not in cfg.tools.builtin_tools

    def test_load_failure_is_warned_not_raised(
        self,
        monkeypatch,
        tmp_path,
        capsys,
    ):
        d1 = tmp_path / "a1"
        d1.mkdir()
        (d1 / "agent.json").write_text("{}")
        monkeypatch.setattr(config_utils, "get_agent_dirs", lambda: [d1])
        import qwenpaw.config.config as cc

        def boom(p):
            raise RuntimeError("bad json")

        monkeypatch.setattr(cc, "load_agent_config", boom)
        pc._remove_tool_plugin_from_agents({"meta": {"tool_name": "t1"}})
        out = capsys.readouterr().out
        assert "Removed tool from" not in out

    def test_no_agent_had_tool(self, monkeypatch, tmp_path, capsys):
        d1 = tmp_path / "a1"
        d1.mkdir()
        (d1 / "agent.json").write_text("{}")
        monkeypatch.setattr(config_utils, "get_agent_dirs", lambda: [d1])
        import qwenpaw.config.config as cc

        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda p: _AgentConfig(),
        )
        pc._remove_tool_plugin_from_agents({"meta": {"tool_name": "t1"}})
        assert "No agents had this tool" in capsys.readouterr().out


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
        assert "Invalid plugin.json" in res.output

    def test_manifest_read_failure_generic(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        d = tmp_path / "src"
        d.mkdir()
        (d / "plugin.json").write_bytes(b"\xff\xfe\x00invalid")
        res = CliRunner().invoke(pc.plugin, ["install", str(d)])
        assert "Failed to read plugin.json" in res.output

    def test_manifest_missing_fields(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        d = tmp_path / "src"
        d.mkdir()
        (d / "plugin.json").write_text(json.dumps({"id": "x"}))
        res = CliRunner().invoke(pc.plugin, ["install", str(d)])
        assert "missing required fields" in res.output

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

        def bad_validate(pid, path, entry):
            raise ImportError("broken")

        monkeypatch.setattr(pc, "_validate_plugin_module", bad_validate)
        res = CliRunner().invoke(pc.plugin, ["install", str(src)])
        assert "validation failed" in res.output
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
        assert "Failed to copy" in res.output

    def test_full_install_with_deps_and_tool_sync(
        self,
        monkeypatch,
        tmp_path,
    ):
        self._offline(monkeypatch)
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        _write_plugin(
            src,
            extra={
                "entry": {"backend": "backend.py"},
                "meta": {"tool_name": "demo_tool"},
            },
        )
        (src / "requirements.txt").write_text("x==1\n")
        monkeypatch.setattr(pc, "_validate_plugin_module", lambda *a: None)
        monkeypatch.setattr(
            pc,
            "_install_requirements_cli",
            lambda req, tgt: True,
        )
        synced = []
        monkeypatch.setattr(
            pc,
            "_sync_tool_plugin_to_agents",
            lambda m: synced.append(m),
        )
        res = CliRunner().invoke(pc.plugin, ["install", str(src)])
        assert res.exit_code == 0
        assert "installed successfully" in res.output
        assert (pdir / "demo" / "plugin.json").is_file()
        assert len(synced) == 1

    def test_requirements_failure_aborts(self, monkeypatch, tmp_path):
        self._offline(monkeypatch)
        _patch_plugins_dir(monkeypatch, tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        _write_plugin(src)
        (src / "requirements.txt").write_text("x==1\n")
        monkeypatch.setattr(pc, "_validate_plugin_module", lambda *a: None)
        monkeypatch.setattr(
            pc,
            "_install_requirements_cli",
            lambda req, tgt: False,
        )
        res = CliRunner().invoke(pc.plugin, ["install", str(src)])
        assert res.exit_code == 0
        assert "installed successfully" not in res.output

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

    def test_offline_uninstall_removes_and_cleans_agents(
        self,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setattr(pc, "_is_running", lambda: False)
        pdir = _patch_plugins_dir(monkeypatch, tmp_path)
        d = pdir / "demo"
        d.mkdir(parents=True)
        _write_plugin(d, extra={"meta": {"tool_name": "t1"}})
        removed = []
        monkeypatch.setattr(
            pc,
            "_remove_tool_plugin_from_agents",
            lambda m: removed.append(m),
        )
        res = CliRunner().invoke(
            pc.plugin,
            ["uninstall", "demo"],
            input="y\n",
        )
        assert res.exit_code == 0
        assert "uninstalled successfully" in res.output
        assert not d.exists()
        assert len(removed) == 1

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

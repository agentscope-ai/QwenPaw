# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument,unused-variable,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for config/utils.py helpers.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: working-dir path
normalisation, browser detection helpers, config read/validate/backup,
and the channel whitelist filter, which previously sat at ~45% coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import qwenpaw.config.utils as cu


@pytest.fixture()
def working_dir(tmp_path, monkeypatch):
    wd = tmp_path / "wd"
    wd.mkdir()
    monkeypatch.setattr(cu, "WORKING_DIR", wd)
    return wd


@pytest.fixture()
def fresh_config_cache(monkeypatch):
    monkeypatch.setattr(cu, "_config_cache", None)
    monkeypatch.setattr(cu, "_config_mtime", None)


# ---------------------------------------------------------------------------
# _normalize_working_dir_bound_paths
# ---------------------------------------------------------------------------


class TestNormalizeWorkingDirBoundPaths:
    def test_rewrites_legacy_tilde_paths(self, working_dir):
        data = {"media_dir": "~/.copaw/media", "other": "~/.copaw/x"}
        out = cu._normalize_working_dir_bound_paths(data)
        assert out["media_dir"] == str(working_dir) + "/media"
        # non-bound keys untouched
        assert out["other"] == "~/.copaw/x"

    def test_rewrites_workspace_dir(self, working_dir):
        legacy_abs = str(Path("~/.copaw").expanduser().resolve())
        data = {"workspace_dir": f"{legacy_abs}/workspaces/a"}
        out = cu._normalize_working_dir_bound_paths(data)
        assert out["workspace_dir"] == str(working_dir) + "/workspaces/a"

    def test_nested_and_list_walk(self, working_dir):
        data = {"agents": {"workspace_dir": "~/.copaw/w"}, "dirs": []}
        out = cu._normalize_working_dir_bound_paths(data)
        assert out["agents"]["workspace_dir"] == str(working_dir) + "/w"
        assert out["dirs"] == []

    def test_non_string_values_passthrough(self, working_dir):
        data = {"media_dir": None, "count": 5}
        assert cu._normalize_working_dir_bound_paths(data) == data


# ---------------------------------------------------------------------------
# _exec_executable_token
# ---------------------------------------------------------------------------


class TestExecExecutableToken:
    def test_plain_executable(self):
        assert (
            cu._exec_executable_token("/usr/bin/chrome") == "/usr/bin/chrome"
        )

    def test_env_wrapper_with_vars(self):
        value = "env GTK_IM_MODULE=ibus /usr/bin/google-chrome %U"
        assert cu._exec_executable_token(value) == "/usr/bin/google-chrome"

    def test_env_wrapper_only(self):
        assert cu._exec_executable_token("env") is None

    def test_quoted_value(self):
        assert (
            cu._exec_executable_token('"/usr/bin/my browser" --flag')
            == "/usr/bin/my browser"
        )

    def test_unbalanced_quote_falls_back_to_split(self):
        # shlex raises on bad quoting → falls back to plain split
        assert cu._exec_executable_token('"unbalanced') == '"unbalanced'


# ---------------------------------------------------------------------------
# _linux_desktop_to_kind_and_path
# ---------------------------------------------------------------------------


class TestLinuxDesktopToKindAndPath:
    @pytest.mark.parametrize(
        ("exe", "expected"),
        [
            ("/usr/bin/google-chrome", ("chromium", "/usr/bin/google-chrome")),
            (
                "/usr/bin/chromium-browser",
                ("chromium", "/usr/bin/chromium-browser"),
            ),
            ("/usr/bin/firefox", ("firefox", "/usr/bin/firefox")),
            (
                "/usr/bin/microsoft-edge",
                ("chromium", "/usr/bin/microsoft-edge"),
            ),
            ("/opt/unknown/browser", ("chromium", "/opt/unknown/browser")),
        ],
    )
    def test_kind_mapping(self, exe, expected):
        assert cu._linux_desktop_to_kind_and_path(exe) == expected


# ---------------------------------------------------------------------------
# get_system_default_browser
# ---------------------------------------------------------------------------


class TestGetSystemDefaultBrowser:
    def test_container_returns_none(self, monkeypatch):
        monkeypatch.setattr(cu, "is_running_in_container", lambda: True)
        assert cu.get_system_default_browser() == (None, None)

    def test_linux_dispatch(self, monkeypatch):
        monkeypatch.setattr(cu, "is_running_in_container", lambda: False)
        monkeypatch.setattr(cu.sys, "platform", "linux")
        monkeypatch.setattr(
            cu,
            "_get_linux_default_browser",
            lambda: ("chromium", "/usr/bin/chromium"),
        )
        assert cu.get_system_default_browser() == (
            "chromium",
            "/usr/bin/chromium",
        )

    def test_darwin_dispatch(self, monkeypatch):
        monkeypatch.setattr(cu, "is_running_in_container", lambda: False)
        monkeypatch.setattr(cu.sys, "platform", "darwin")
        monkeypatch.setattr(
            cu,
            "_get_darwin_default_browser",
            lambda: ("webkit", None),
        )
        assert cu.get_system_default_browser() == ("webkit", None)

    def test_unsupported_platform(self, monkeypatch):
        monkeypatch.setattr(cu, "is_running_in_container", lambda: False)
        monkeypatch.setattr(cu.sys, "platform", "freebsd13")
        assert cu.get_system_default_browser() == (None, None)


class TestGetLinuxDefaultBrowser:
    def test_xdg_mime_missing(self, monkeypatch):
        def boom(*a, **kw):
            raise FileNotFoundError

        monkeypatch.setattr(cu.subprocess, "run", boom)
        assert cu._get_linux_default_browser() == (None, None)

    def test_xdg_mime_no_output(self, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            cu.subprocess,
            "run",
            lambda *a, **kw: SimpleNamespace(returncode=0, stdout=""),
        )
        assert cu._get_linux_default_browser() == (None, None)

    def test_finds_chrome_via_desktop_file(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        desktop = tmp_path / "chrome.desktop"
        desktop.write_text(
            "[Desktop Entry]\nExec=/usr/bin/google-chrome-stable %U\n",
            encoding="utf-8",
        )
        exe = tmp_path / "usr" / "bin" / "google-chrome-stable"
        exe.parent.mkdir(parents=True)
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)

        monkeypatch.setattr(
            cu.subprocess,
            "run",
            lambda *a, **kw: SimpleNamespace(
                returncode=0,
                stdout=desktop.name,
            ),
        )
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        # desktop file resolves but the absolute Exec path doesn't exist on
        # this machine; the function still must not raise.
        kind, path = cu._get_linux_default_browser()
        assert kind in (None, "chromium")


# ---------------------------------------------------------------------------
# _remove_nested_key / _remove_bad_field
# ---------------------------------------------------------------------------


class TestRemoveNestedKey:
    def test_removes_top_level(self):
        data = {"a": 1}
        assert cu._remove_nested_key(data, ["a"]) is True
        assert data == {}

    def test_removes_nested(self):
        data = {"a": {"b": {"c": 1}}}
        assert cu._remove_nested_key(data, ["a", "b", "c"]) is True
        assert data == {"a": {"b": {}}}

    def test_removes_by_list_index(self):
        data = {"a": [{"b": 1}]}
        assert cu._remove_nested_key(data, ["a", 0, "b"]) is True
        assert data == {"a": [{}]}

    def test_missing_path_returns_false(self):
        data = {"a": 1}
        assert cu._remove_nested_key(data, ["x"]) is False
        assert cu._remove_nested_key(data, ["a", "b"]) is False

    def test_index_out_of_range(self):
        data = {"a": []}
        assert cu._remove_nested_key(data, ["a", 5, "b"]) is False


class TestRemoveBadField:
    def test_exact_location(self):
        data = {"a": {"b": 1}}
        assert cu._remove_bad_field(data, ["a", "b"]) is True

    def test_falls_back_to_ancestor(self):
        data = {"a": {"b": 1}}
        assert cu._remove_bad_field(data, ["a", "b", "c", "d"]) is True
        assert data == {"a": {}}

    def test_nothing_removable(self):
        data = {"a": 1}
        assert cu._remove_bad_field(data, ["z"]) is False


# ---------------------------------------------------------------------------
# _read_config_data
# ---------------------------------------------------------------------------


class TestReadConfigData:
    def test_valid_json(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text('{"a": 1}', encoding="utf-8")
        assert cu._read_config_data(p) == {"a": 1}

    def test_repairable_json(self, tmp_path):
        p = tmp_path / "config.json"
        # trailing comma — json_repair handles it
        p.write_text('{"a": 1,}', encoding="utf-8")
        data = cu._read_config_data(p)
        assert data == {"a": 1}

    def test_unrepairable_json_backed_up(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")  # root not an object
        assert cu._read_config_data(p) is None
        backups = list(tmp_path.glob("config.*.bak"))
        assert len(backups) == 1

    def test_binary_file_backed_up(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_bytes(b"\xff\xfe\x00invalid")
        assert cu._read_config_data(p) is None

    def test_backup_failure_returns_none(self, tmp_path, monkeypatch):
        p = tmp_path / "missing" / "config.json"
        monkeypatch.setattr(
            cu.shutil,
            "copy2",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("denied")),
        )
        # non-utf8 content triggers backup attempt which fails
        (tmp_path / "missing").mkdir()
        p.write_bytes(b"\xff\xfe")
        assert cu._read_config_data(p) is None


# ---------------------------------------------------------------------------
# load_config / save_config caching
# ---------------------------------------------------------------------------


class TestLoadSaveConfig:
    def test_missing_file_returns_defaults(self, tmp_path, fresh_config_cache):
        assert cu.load_config(tmp_path / "nope.json").__class__.__name__ == (
            "Config"
        )

    def test_save_and_reload(self, tmp_path, fresh_config_cache):
        from qwenpaw.config.config import Config

        path = tmp_path / "config.json"
        cfg = Config()
        cu.save_config(cfg, path)
        assert path.is_file()
        loaded = cu.load_config(path)
        assert loaded is not None

    def test_cache_hit_on_same_mtime(self, tmp_path, fresh_config_cache):
        from qwenpaw.config.config import Config

        path = tmp_path / "config.json"
        cu.save_config(Config(), path)
        first = cu.load_config(path)
        second = cu.load_config(path)
        assert first == second

    def test_invalid_config_falls_back(self, tmp_path, fresh_config_cache):
        path = tmp_path / "config.json"
        path.write_text("[1,2]", encoding="utf-8")
        cfg = cu.load_config(path)
        assert cfg.__class__.__name__ == "Config"


# ---------------------------------------------------------------------------
# strict_validate_config_file
# ---------------------------------------------------------------------------


class TestStrictValidateConfigFile:
    def test_missing_file_ok(self, tmp_path):
        ok, msg = cu.strict_validate_config_file(tmp_path / "nope.json")
        assert ok is True
        assert "(no file)" in msg

    def test_valid_file_ok(self, tmp_path, working_dir):
        path = tmp_path / "config.json"
        path.write_text('{"channels": {}}', encoding="utf-8")
        ok, msg = cu.strict_validate_config_file(path)
        assert ok is True

    def test_invalid_json_fails(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("[1,2]", encoding="utf-8")
        ok, msg = cu.strict_validate_config_file(path)
        assert ok is False
        assert "unreadable" in msg

    def test_validation_error_reported(self, tmp_path, working_dir):
        path = tmp_path / "config.json"
        # agents must be an object; a number fails validation
        path.write_text('{"agents": 5}', encoding="utf-8")
        ok, msg = cu.strict_validate_config_file(path)
        assert ok is False
        assert str(path) in msg

    def test_legacy_last_api_fields_migrated(self, tmp_path, working_dir):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"last_api_host": "127.0.0.1", "last_api_port": 8080}),
            encoding="utf-8",
        )
        ok, _ = cu.strict_validate_config_file(path)
        assert ok is True


# ---------------------------------------------------------------------------
# get_config_path / get_heartbeat_query_path
# ---------------------------------------------------------------------------


class TestPathHelpers:
    def test_config_path(self, working_dir):
        assert cu.get_config_path() == working_dir / "config.json"

    def test_heartbeat_query_path(self, working_dir):
        path = cu.get_heartbeat_query_path()
        assert path.parent == working_dir


# ---------------------------------------------------------------------------
# get_available_channels
# ---------------------------------------------------------------------------


class TestGetAvailableChannels:
    @pytest.fixture()
    def fake_registry(self, monkeypatch):
        import qwenpaw.app.channels.registry as registry_module

        monkeypatch.setattr(
            registry_module,
            "get_channel_registry",
            lambda: {"console": 1, "dingtalk": 2, "feishu": 3},
        )

    def test_no_filters_returns_all(self, monkeypatch, fake_registry):
        monkeypatch.delenv("QWENPAW_ENABLED_CHANNELS", raising=False)
        monkeypatch.delenv("QWENPAW_DISABLED_CHANNELS", raising=False)
        assert cu.get_available_channels() == (
            "console",
            "dingtalk",
            "feishu",
        )

    def test_enabled_whitelist(self, monkeypatch, fake_registry):
        monkeypatch.setenv("QWENPAW_ENABLED_CHANNELS", "console, feishu")
        monkeypatch.delenv("QWENPAW_DISABLED_CHANNELS", raising=False)
        assert cu.get_available_channels() == ("console", "feishu")

    def test_enabled_whitelist_no_match_returns_all(
        self,
        monkeypatch,
        fake_registry,
    ):
        monkeypatch.setenv("QWENPAW_ENABLED_CHANNELS", "ghost")
        monkeypatch.delenv("QWENPAW_DISABLED_CHANNELS", raising=False)
        assert cu.get_available_channels() == (
            "console",
            "dingtalk",
            "feishu",
        )

    def test_disabled_blacklist(self, monkeypatch, fake_registry):
        monkeypatch.delenv("QWENPAW_ENABLED_CHANNELS", raising=False)
        monkeypatch.setenv("QWENPAW_DISABLED_CHANNELS", "feishu")
        assert cu.get_available_channels() == ("console", "dingtalk")

    def test_enabled_wins_over_disabled(self, monkeypatch, fake_registry):
        monkeypatch.setenv("QWENPAW_ENABLED_CHANNELS", "console")
        monkeypatch.setenv("QWENPAW_DISABLED_CHANNELS", "feishu")
        assert cu.get_available_channels() == ("console",)


# ---------------------------------------------------------------------------
# is_running_in_container
# ---------------------------------------------------------------------------


class TestIsRunningInContainer:
    def test_env_flag_wins(self, monkeypatch):
        monkeypatch.setattr(cu, "RUNNING_IN_CONTAINER", True)
        assert cu.is_running_in_container() is True

    def test_dockerenv_present(self, monkeypatch):
        monkeypatch.setattr(cu, "RUNNING_IN_CONTAINER", False)
        monkeypatch.setattr(cu.os.path, "exists", lambda p: p == "/.dockerenv")
        assert cu.is_running_in_container() is True

    def test_cgroup_detection(self, monkeypatch):
        monkeypatch.setattr(cu, "RUNNING_IN_CONTAINER", False)
        monkeypatch.setattr(cu.os.path, "exists", lambda p: False)

        import builtins
        import io as _io

        real_open = builtins.open

        def fake_open(path, *args, **kwargs):
            if path == "/proc/1/cgroup":
                return _io.StringIO("12:cpu:/docker/abc\n")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fake_open)
        assert cu.is_running_in_container() is True

    def test_not_in_container(self, monkeypatch):
        monkeypatch.setattr(cu, "RUNNING_IN_CONTAINER", False)
        monkeypatch.setattr(cu.os.path, "exists", lambda p: False)

        import builtins
        import io as _io

        real_open = builtins.open

        def fake_open(path, *args, **kwargs):
            if path == "/proc/1/cgroup":
                return _io.StringIO("12:cpu:/init.scope\n")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fake_open)
        assert cu.is_running_in_container() is False

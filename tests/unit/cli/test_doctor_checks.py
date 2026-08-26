# -*- coding: utf-8 -*-
"""Unit tests for cli/doctor_checks.py read-only diagnostics.

Every function under test is side-effect free (read-only checks for
``qwenpaw doctor``); tests monkeypatch module-level paths and the
few external collaborators (disk usage, provider manager, agent config
loading) so the logic is exercised deterministically in-process.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,unused-variable,use-dict-literal,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import qwenpaw.cli.doctor_checks as dc


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_working_dir(tmp_path, monkeypatch):
    """Point module-level WORKING_DIR at a temp dir."""
    wd = tmp_path / "working"
    wd.mkdir()
    monkeypatch.setattr(dc, "WORKING_DIR", wd)
    return wd


def _make_config(profiles: dict[str, Any] | None = None):
    from qwenpaw.config.config import Config

    cfg = Config()
    cfg.agents.profiles = profiles or {}
    return cfg


def _profile_ref(agent_id: str, workspace_dir: str):
    from qwenpaw.config.config import AgentProfileRef

    return AgentProfileRef(id=agent_id, workspace_dir=workspace_dir)


# ---------------------------------------------------------------------------
# _resolve_existing_path_anchor
# ---------------------------------------------------------------------------


class TestResolveExistingPathAnchor:
    def test_existing_path_returns_itself(self, tmp_path):
        assert dc._resolve_existing_path_anchor(tmp_path) == tmp_path

    def test_missing_child_resolves_to_existing_ancestor(self, tmp_path):
        missing = tmp_path / "nope" / "deep"
        assert dc._resolve_existing_path_anchor(missing) == tmp_path

    def test_exists_oserror_returns_none(self, tmp_path, monkeypatch):
        def _boom(self):
            raise OSError("denied")

        monkeypatch.setattr(Path, "exists", _boom)
        assert dc._resolve_existing_path_anchor(tmp_path / "x") is None


# ---------------------------------------------------------------------------
# check_app_log_writable
# ---------------------------------------------------------------------------


class TestCheckAppLogWritable:
    def test_existing_writable_file(self, fake_working_dir, monkeypatch):
        log = fake_working_dir / "app.log"
        log.write_text("x")
        monkeypatch.setattr(dc, "APP_LOG_BASENAME", "app.log")
        ok, msg = dc.check_app_log_writable()
        assert ok is True
        assert "writable" in msg

    def test_existing_path_is_dir(self, fake_working_dir, monkeypatch):
        (fake_working_dir / "app.log").mkdir()
        monkeypatch.setattr(dc, "APP_LOG_BASENAME", "app.log")
        ok, msg = dc.check_app_log_writable()
        assert ok is False
        assert "not a regular file" in msg

    def test_existing_file_not_writable(self, fake_working_dir, monkeypatch):
        log = fake_working_dir / "app.log"
        log.write_text("x")
        monkeypatch.setattr(dc, "APP_LOG_BASENAME", "app.log")
        monkeypatch.setattr(dc.os, "access", lambda p, m: False)
        ok, msg = dc.check_app_log_writable()
        assert ok is False
        assert "cannot write" in msg

    def test_parent_missing(self, fake_working_dir, monkeypatch):
        monkeypatch.setattr(dc, "APP_LOG_BASENAME", "subdir/app.log")
        ok, msg = dc.check_app_log_writable()
        assert ok is False
        assert "directory does not exist" in msg

    def test_parent_writable_no_file(self, fake_working_dir, monkeypatch):
        monkeypatch.setattr(dc, "APP_LOG_BASENAME", "fresh.log")
        ok, msg = dc.check_app_log_writable()
        assert ok is True
        assert "parent directory appears writable" in msg

    def test_parent_not_writable(self, fake_working_dir, monkeypatch):
        monkeypatch.setattr(dc, "APP_LOG_BASENAME", "fresh.log")
        monkeypatch.setattr(dc.os, "access", lambda p, m: False)
        ok, msg = dc.check_app_log_writable()
        assert ok is False
        assert "not writable" in msg


# ---------------------------------------------------------------------------
# check_browser_readiness
# ---------------------------------------------------------------------------


class TestCheckBrowserReadiness:
    def test_experimental_track(self, fake_working_dir):
        cfg = _make_config()
        cfg.browser.experimental = True
        ok, msg = dc.check_browser_readiness(cfg)
        assert ok is True
        assert "unified browser track" in msg

    def test_experimental_links_import_fails(self, monkeypatch):
        cfg = _make_config()
        cfg.browser.experimental = True
        monkeypatch.setitem(sys.modules, "qwenpaw.browser.runtime.links", None)
        ok, msg = dc.check_browser_readiness(cfg)
        assert ok is False
        assert "unavailable" in msg

    def test_stable_track_playwright_importable(self, monkeypatch):
        cfg = _make_config()
        cfg.browser.experimental = False
        fake = types.ModuleType("playwright.async_api")
        fake.async_playwright = lambda: None
        monkeypatch.setitem(
            sys.modules,
            "playwright",
            types.ModuleType("playwright"),
        )
        monkeypatch.setitem(sys.modules, "playwright.async_api", fake)
        ok, msg = dc.check_browser_readiness(cfg)
        assert ok is True
        assert "stable browser track" in msg

    def test_stable_track_playwright_missing(self, monkeypatch):
        cfg = _make_config()
        cfg.browser.experimental = False

        def _raise_import(name, *a, **k):
            if name.startswith("playwright"):
                raise ImportError("no playwright")
            return real_import(name, *a, **k)

        real_import = __import__
        monkeypatch.setattr("builtins.__import__", _raise_import)
        ok, msg = dc.check_browser_readiness(cfg)
        assert ok is False
        assert "requires Playwright" in msg


# ---------------------------------------------------------------------------
# check_agent_workspace_writable
# ---------------------------------------------------------------------------


class TestCheckAgentWorkspaceWritable:
    def test_no_existing_dirs(self):
        cfg = _make_config({"a": _profile_ref("a", "/nonexistent/ws")})
        ok, msg = dc.check_agent_workspace_writable(cfg)
        assert ok is True
        assert "skipped" in msg

    def test_writable_dirs(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        ok, msg = dc.check_agent_workspace_writable(cfg)
        assert ok is True
        assert "1 workspace dir(s) writable" in msg

    def test_not_writable_reported(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        monkeypatch.setattr(dc.os, "access", lambda p, m: False)
        ok, msg = dc.check_agent_workspace_writable(cfg)
        assert ok is False
        assert "a:" in msg


# ---------------------------------------------------------------------------
# startup_extra_volume_disk_notes
# ---------------------------------------------------------------------------


class _FakeAnchor:
    def __init__(self, dev: int, label: str):
        self._dev = dev
        self.label = label

    def stat(self):
        return SimpleNamespace(st_dev=self._dev)

    def __str__(self):
        return f"/fake/{self.label}"


class TestStartupExtraVolumeDiskNotes:
    def test_working_dir_stat_oserror(self, tmp_path, monkeypatch):
        class _Wd:
            def stat(self):
                raise OSError("no dev")

        monkeypatch.setattr(dc, "WORKING_DIR", _Wd())
        assert dc.startup_extra_volume_disk_notes(None) == []

    def test_low_free_space_on_other_volume(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dc, "WORKING_DIR", _FakeAnchor(1, "wd"))
        monkeypatch.setattr(dc, "SECRET_DIR", Path(str(tmp_path)))
        anchors = {str(tmp_path): _FakeAnchor(2, "secret")}

        def _anchor(p):
            return anchors.get(str(p))

        monkeypatch.setattr(dc, "_resolve_existing_path_anchor", _anchor)
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=0.1 * 1024**3),
        )
        notes = dc.startup_extra_volume_disk_notes(None)
        assert len(notes) == 1
        assert "below" in notes[0]

    def test_same_volume_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dc, "WORKING_DIR", _FakeAnchor(1, "wd"))
        monkeypatch.setattr(dc, "SECRET_DIR", Path(str(tmp_path)))
        monkeypatch.setattr(
            dc,
            "_resolve_existing_path_anchor",
            lambda p: _FakeAnchor(1, "same"),
        )
        notes = dc.startup_extra_volume_disk_notes(None)
        assert notes == []

    def test_anchor_none_and_oserror_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dc, "WORKING_DIR", _FakeAnchor(1, "wd"))
        monkeypatch.setattr(dc, "SECRET_DIR", Path(str(tmp_path)))
        calls = {"n": 0}

        def _anchor(p):
            calls["n"] += 1
            if calls["n"] == 1:
                return None

            class _Boom:
                def stat(self):
                    raise OSError("stat failed")

            return _Boom()

        monkeypatch.setattr(dc, "_resolve_existing_path_anchor", _anchor)
        assert dc.startup_extra_volume_disk_notes(None) == []

    def test_profile_workspace_considered(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(dc, "WORKING_DIR", _FakeAnchor(1, "wd"))
        monkeypatch.setattr(dc, "SECRET_DIR", tmp_path / "no-such")
        monkeypatch.setattr(
            dc,
            "_resolve_existing_path_anchor",
            lambda p: _FakeAnchor(3, "ws") if str(p) == str(ws) else None,
        )
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=100 * 1024**3),
        )
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        assert dc.startup_extra_volume_disk_notes(cfg) == []

    def test_disk_usage_oserror_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dc, "WORKING_DIR", _FakeAnchor(1, "wd"))
        monkeypatch.setattr(dc, "SECRET_DIR", Path(str(tmp_path)))
        monkeypatch.setattr(
            dc,
            "_resolve_existing_path_anchor",
            lambda p: _FakeAnchor(9, "x"),
        )

        def _du(p):
            raise OSError("no usage")

        monkeypatch.setattr(dc.shutil, "disk_usage", _du)
        assert dc.startup_extra_volume_disk_notes(None) == []


# ---------------------------------------------------------------------------
# environment_summary_lines
# ---------------------------------------------------------------------------


class TestEnvironmentSummaryLines:
    def test_basic_lines(self, fake_working_dir, monkeypatch):
        monkeypatch.delenv("QWENPAW_WORKING_DIR", raising=False)
        monkeypatch.delenv("COPAW_WORKING_DIR", raising=False)
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=10 * 1024**3),
        )
        lines = dc.environment_summary_lines()
        joined = "\n".join(lines)
        assert "python version:" in joined
        assert "qwenpaw version:" in joined
        assert "working_dir:" in joined
        assert "disk free (working dir volume)" in joined
        assert "(unknown)" in joined  # no server env provided

    def test_server_environment_provided(self, fake_working_dir, monkeypatch):
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=10 * 1024**3),
        )
        lines = dc.environment_summary_lines(
            server_python_environment="venv-x",
        )
        assert any(
            "qwenpaw_python_environment: venv-x" in line for line in lines
        )

    def test_server_note_fallback(self, fake_working_dir, monkeypatch):
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=10 * 1024**3),
        )
        lines = dc.environment_summary_lines(server_python_note="no server")
        assert any("no server" in line for line in lines)

    def test_env_var_qwenpaw(self, fake_working_dir, monkeypatch):
        monkeypatch.setenv("QWENPAW_WORKING_DIR", "/custom/wd")
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=10 * 1024**3),
        )
        lines = dc.environment_summary_lines()
        assert any(
            "QWENPAW_WORKING_DIR (env): /custom/wd" in line for line in lines
        )

    def test_env_var_legacy(self, fake_working_dir, monkeypatch):
        monkeypatch.delenv("QWENPAW_WORKING_DIR", raising=False)
        monkeypatch.setenv("COPAW_WORKING_DIR", "/legacy/wd")
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=10 * 1024**3),
        )
        lines = dc.environment_summary_lines()
        assert any("COPAW_WORKING_DIR (env, legacy)" in line for line in lines)

    def test_old_sqlite_note(self, fake_working_dir, monkeypatch):
        monkeypatch.setattr(dc.sqlite3, "sqlite_version", "3.30.0")
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=10 * 1024**3),
        )
        lines = dc.environment_summary_lines()
        assert any("SQLite < 3.35" in line for line in lines)

    def test_bad_sqlite_version_swallowed(self, fake_working_dir, monkeypatch):
        monkeypatch.setattr(dc.sqlite3, "sqlite_version", "not.a.version")
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=10 * 1024**3),
        )
        lines = dc.environment_summary_lines()  # must not raise
        assert lines

    def test_low_disk_note(self, fake_working_dir, monkeypatch):
        monkeypatch.setattr(
            dc.shutil,
            "disk_usage",
            lambda p: SimpleNamespace(free=0.1 * 1024**3),
        )
        lines = dc.environment_summary_lines()
        assert any("very low free space" in line for line in lines)

    def test_disk_usage_oserror(self, fake_working_dir, monkeypatch):
        def _du(p):
            raise OSError("no")

        monkeypatch.setattr(dc.shutil, "disk_usage", _du)
        lines = dc.environment_summary_lines()
        assert any("could not stat" in line for line in lines)


# ---------------------------------------------------------------------------
# load_raw_config_dict / scan_unknown_config_keys
# ---------------------------------------------------------------------------


class TestLoadRawConfigDict:
    def test_missing_file(self, monkeypatch):
        monkeypatch.setattr(
            dc,
            "get_config_path",
            lambda: Path("/nonexistent/config.json"),
        )
        assert dc.load_raw_config_dict() is None

    def test_dict_data(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{}")
        monkeypatch.setattr(dc, "get_config_path", lambda: cfg_file)
        monkeypatch.setattr(dc, "_read_config_data", lambda p: {"a": 1})
        assert dc.load_raw_config_dict() == {"a": 1}

    def test_non_dict_data(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("[]")
        monkeypatch.setattr(dc, "get_config_path", lambda: cfg_file)
        monkeypatch.setattr(dc, "_read_config_data", lambda p: [1, 2])
        assert dc.load_raw_config_dict() is None


class TestScanUnknownConfigKeys:
    def test_known_keys_clean(self):
        from qwenpaw.config.config import Config

        raw = {k: {} for k in list(Config.model_fields.keys())[:3]}
        assert dc.scan_unknown_config_keys(raw) == []

    def test_unknown_root_key(self):
        found = dc.scan_unknown_config_keys({"totally_unknown_key": 1})
        assert len(found) == 1
        assert "top-level key" in found[0]

    def test_legacy_api_keys_allowed(self):
        found = dc.scan_unknown_config_keys(
            {"last_api_host": "h", "last_api_port": 1},
        )
        assert found == []

    def test_unknown_section_keys(self):
        raw = {
            "agents": {"bogus_agent_key": 1},
            "tools": {"bogus_tool_key": 1},
            "security": {"bogus_security_key": 1},
            "mcp": {"bogus_mcp_key": 1},
            "channels": {"bogus_channel": {}},
        }
        found = dc.scan_unknown_config_keys(raw)
        assert any("agents." in f for f in found)
        assert any("tools." in f for f in found)
        assert any("security." in f for f in found)
        assert any("mcp." in f for f in found)
        assert any("channels." in f and "plugin" in f for f in found)

    def test_non_dict_sections_ignored(self):
        assert dc.scan_unknown_config_keys({"agents": "notdict"}) == []


# ---------------------------------------------------------------------------
# legacy_single_agent_workspace_note / check_agent_profile_workspaces
# ---------------------------------------------------------------------------


class TestLegacySingleAgentWorkspaceNote:
    def test_multiple_profiles_none(self, tmp_path):
        cfg = _make_config(
            {
                "default": _profile_ref("default", str(tmp_path)),
                "other": _profile_ref("other", str(tmp_path)),
            },
        )
        assert dc.legacy_single_agent_workspace_note(cfg) is None

    def test_single_non_default_none(self, tmp_path):
        cfg = _make_config({"solo": _profile_ref("solo", str(tmp_path))})
        assert dc.legacy_single_agent_workspace_note(cfg) is None

    def test_agent_json_present_none(self, tmp_path):
        (tmp_path / "agent.json").write_text("{}")
        cfg = _make_config({"default": _profile_ref("default", str(tmp_path))})
        assert dc.legacy_single_agent_workspace_note(cfg) is None

    def test_missing_agent_json_notes_migration(self, tmp_path):
        cfg = _make_config(
            {"default": _profile_ref("default", str(tmp_path / "ws"))},
        )
        note = dc.legacy_single_agent_workspace_note(cfg)
        assert note is not None
        assert "migration" in note

    def test_non_ref_profile_none(self, tmp_path):
        cfg = _make_config({"default": object()})
        assert dc.legacy_single_agent_workspace_note(cfg) is None


class TestCheckAgentProfileWorkspaces:
    def test_ok(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "agent.json").write_text("{}")
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        ok, msg = dc.check_agent_profile_workspaces(cfg)
        assert ok is True
        assert "1 agent profile(s)" in msg

    def test_missing_dir(self, tmp_path):
        cfg = _make_config({"a": _profile_ref("a", str(tmp_path / "nope"))})
        ok, msg = dc.check_agent_profile_workspaces(cfg)
        assert ok is False
        assert "not a directory" in msg

    def test_missing_agent_json(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        ok, msg = dc.check_agent_profile_workspaces(cfg)
        assert ok is False
        assert "missing" in msg


# ---------------------------------------------------------------------------
# check_cron_jobs_files
# ---------------------------------------------------------------------------


class TestCheckCronJobsFiles:
    @pytest.fixture(autouse=True)
    def _no_legacy_jobs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            dc,
            "get_jobs_path",
            lambda: tmp_path / "no-legacy-jobs.json",
        )

    def test_no_jobs_files(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        ok, msg = dc.check_cron_jobs_files(cfg)
        assert ok is True
        assert "no jobs.json" in msg

    def test_valid_jobs_file(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "jobs.json").write_text(json.dumps({"jobs": []}))
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        ok, msg = dc.check_cron_jobs_files(cfg)
        assert ok is True
        assert "a: 0 job(s)" in msg

    def test_invalid_json(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "jobs.json").write_text("{bad")
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        ok, msg = dc.check_cron_jobs_files(cfg)
        assert ok is False
        assert "JSON error" in msg

    def test_schema_error(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "jobs.json").write_text(json.dumps({"jobs": "notalist"}))
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        ok, msg = dc.check_cron_jobs_files(cfg)
        assert ok is False
        assert "schema" in msg

    def test_legacy_root_file(self, tmp_path, monkeypatch):
        legacy = tmp_path / "jobs.json"
        legacy.write_text(json.dumps({"jobs": []}))
        monkeypatch.setattr(dc, "get_jobs_path", lambda: legacy)
        cfg = _make_config({})
        ok, msg = dc.check_cron_jobs_files(cfg)
        assert ok is True
        assert "(root)" in msg

    def test_legacy_root_bad_json(self, tmp_path, monkeypatch):
        legacy = tmp_path / "jobs.json"
        legacy.write_text("nope")
        monkeypatch.setattr(dc, "get_jobs_path", lambda: legacy)
        cfg = _make_config({})
        ok, msg = dc.check_cron_jobs_files(cfg)
        assert ok is False
        assert "legacy root" in msg


# ---------------------------------------------------------------------------
# playwright cache helpers
# ---------------------------------------------------------------------------


class TestPlaywrightCacheHelpers:
    def test_cache_roots_env_and_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "pw"))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        roots = dc._ms_playwright_browser_cache_roots()
        assert tmp_path / "pw" in roots

    def test_cache_roots_localappdata(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        roots = dc._ms_playwright_browser_cache_roots()
        assert tmp_path / "ms-playwright" in roots

    def test_chromium_present(self, tmp_path, monkeypatch):
        root = tmp_path / "cache"
        (root / "chromium-1234").mkdir(parents=True)
        monkeypatch.setattr(
            dc,
            "_ms_playwright_browser_cache_roots",
            lambda: [root],
        )
        assert dc._playwright_chromium_bundle_present() is True

    def test_chromium_absent(self, tmp_path, monkeypatch):
        root = tmp_path / "cache"
        (root / "firefox-1").mkdir(parents=True)
        monkeypatch.setattr(
            dc,
            "_ms_playwright_browser_cache_roots",
            lambda: [root],
        )
        assert dc._playwright_chromium_bundle_present() is False

    def test_root_iterdir_oserror(self, tmp_path, monkeypatch):
        class _Root:
            def is_dir(self):
                return True

            def iterdir(self):
                raise OSError("denied")

        monkeypatch.setattr(
            dc,
            "_ms_playwright_browser_cache_roots",
            lambda: [_Root()],
        )
        assert dc._playwright_chromium_bundle_present() is False


# ---------------------------------------------------------------------------
# security_baseline_notes / embedding helpers
# ---------------------------------------------------------------------------


class TestSecurityBaselineNotes:
    def test_all_enabled_no_notes(self):
        cfg = _make_config()
        assert dc.security_baseline_notes(cfg) == []

    def test_all_disabled_notes(self):
        cfg = _make_config()
        cfg.security.tool_guard.enabled = False
        cfg.security.skill_scanner.mode = "off"
        cfg.security.file_guard.enabled = False
        notes = dc.security_baseline_notes(cfg)
        assert len(notes) == 3


class TestEmbeddingHelpers:
    @pytest.mark.parametrize(
        "backend,key,expected",
        [
            ("ollama", "", True),
            ("dashscope", "sk-x", True),
            ("dashscope", "", False),
            ("dashscope", "   ", False),
        ],
    )
    def test_has_credentials(self, backend, key, expected):
        assert dc._embedding_has_credentials(backend, key) == expected

    def test_memory_embedding_notes_no_key(self, monkeypatch):
        cfg = _make_config({"a": _profile_ref("a", "/nonexistent")})
        fake_ac = SimpleNamespace(
            running=SimpleNamespace(
                reme_light_memory_config=SimpleNamespace(
                    embedding_model_config=SimpleNamespace(
                        backend="dashscope",
                        api_key="",
                    ),
                    auto_memory_search_config=SimpleNamespace(enabled=True),
                ),
            ),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: fake_ac)
        notes = dc.memory_embedding_notes(cfg)
        assert len(notes) == 1
        assert "a:" in notes[0]

    def test_memory_embedding_notes_ok(self, monkeypatch):
        cfg = _make_config({"a": _profile_ref("a", "/nonexistent")})
        fake_ac = SimpleNamespace(
            running=SimpleNamespace(
                reme_light_memory_config=SimpleNamespace(
                    embedding_model_config=SimpleNamespace(
                        backend="dashscope",
                        api_key="sk-1",
                    ),
                    auto_memory_search_config=SimpleNamespace(enabled=True),
                ),
            ),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: fake_ac)
        assert dc.memory_embedding_notes(cfg) == []

    def test_memory_embedding_notes_disabled(self, monkeypatch):
        cfg = _make_config({"a": _profile_ref("a", "/nonexistent")})
        fake_ac = SimpleNamespace(
            running=SimpleNamespace(
                reme_light_memory_config=SimpleNamespace(
                    embedding_model_config=SimpleNamespace(
                        backend="dashscope",
                        api_key="",
                    ),
                    auto_memory_search_config=SimpleNamespace(enabled=False),
                ),
            ),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: fake_ac)
        assert dc.memory_embedding_notes(cfg) == []

    def test_memory_embedding_notes_load_fails(self, monkeypatch):
        cfg = _make_config({"a": _profile_ref("a", "/nonexistent")})

        def _boom(aid):
            raise RuntimeError("no")

        monkeypatch.setattr(dc, "load_agent_config", _boom)
        assert dc.memory_embedding_notes(cfg) == []


# ---------------------------------------------------------------------------
# workspace_hygiene_notes
# ---------------------------------------------------------------------------


class TestWorkspaceHygieneNotes:
    def test_large_prompt_file(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "AGENTS.md").write_bytes(b"x" * (351 * 1024))
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        monkeypatch.setattr(dc, "MEMORY_DIR", tmp_path / "no-mem")
        notes = dc.workspace_hygiene_notes(cfg)
        assert len(notes) == 1
        assert "AGENTS.md" in notes[0]

    def test_many_tool_results_and_dialog(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        (ws / "tool_results").mkdir(parents=True)
        (ws / "dialog").mkdir()
        for i in range(401):
            (ws / "tool_results" / f"f{i}").write_text("")
        for i in range(201):
            (ws / "dialog" / f"d{i}").write_text("")
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        monkeypatch.setattr(dc, "MEMORY_DIR", tmp_path / "no-mem")
        notes = dc.workspace_hygiene_notes(cfg)
        assert any("tool_results" in n for n in notes)
        assert any("dialog/" in n for n in notes)

    def test_missing_workspace_skipped(self, tmp_path, monkeypatch):
        cfg = _make_config({"a": _profile_ref("a", str(tmp_path / "gone"))})
        monkeypatch.setattr(dc, "MEMORY_DIR", tmp_path / "no-mem")
        assert dc.workspace_hygiene_notes(cfg) == []

    def test_huge_memory_tree(self, tmp_path, monkeypatch):
        class _FakeMem:
            def is_dir(self):
                return True

            def rglob(self, pattern):
                return [SimpleNamespace(is_file=lambda: True)] * 5001

        monkeypatch.setattr(dc, "MEMORY_DIR", _FakeMem())
        cfg = _make_config({})
        notes = dc.workspace_hygiene_notes(cfg)
        assert len(notes) == 1
        assert "memory tree" in notes[0]

    def test_stat_oserror_skipped(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        monkeypatch.setattr(dc, "MEMORY_DIR", tmp_path / "no-mem")
        real_is_file = Path.is_file
        real_stat = Path.stat

        def _is_file(self):
            if self.name == "SOUL.md":
                return True
            return real_is_file(self)

        def _stat(self, *args, **kwargs):
            if self.name == "SOUL.md":
                raise OSError("no")
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "is_file", _is_file)
        monkeypatch.setattr(Path, "stat", _stat)
        assert dc.workspace_hygiene_notes(cfg) == []


# ---------------------------------------------------------------------------
# _read_workspace_agent_json / check_agent_json_profiles
# ---------------------------------------------------------------------------


class TestReadWorkspaceAgentJson:
    def test_valid(self, tmp_path):
        (tmp_path / "agent.json").write_text(json.dumps({"a": 1}))
        ref = _profile_ref("a", str(tmp_path))
        data = dc._read_workspace_agent_json(ref)
        assert data is not None
        assert data.get("a") == 1

    def test_missing(self, tmp_path):
        ref = _profile_ref("a", str(tmp_path))
        assert dc._read_workspace_agent_json(ref) is None

    def test_bad_json(self, tmp_path):
        (tmp_path / "agent.json").write_text("{oops")
        ref = _profile_ref("a", str(tmp_path))
        assert dc._read_workspace_agent_json(ref) is None

    def test_non_dict(self, tmp_path):
        (tmp_path / "agent.json").write_text("[1,2]")
        ref = _profile_ref("a", str(tmp_path))
        assert dc._read_workspace_agent_json(ref) is None

    def test_normalize_failure_swallowed(self, tmp_path, monkeypatch):
        (tmp_path / "agent.json").write_text(json.dumps({"a": 1}))
        ref = _profile_ref("a", str(tmp_path))

        def _boom(data):
            raise RuntimeError("no")

        monkeypatch.setattr(dc, "_normalize_working_dir_bound_paths", _boom)
        data = dc._read_workspace_agent_json(ref)
        assert data == {"a": 1}


class TestCheckAgentJsonProfiles:
    def test_no_agent_json(self, tmp_path):
        cfg = _make_config({"a": _profile_ref("a", str(tmp_path))})
        ok, msg = dc.check_agent_json_profiles(cfg)
        assert ok is True
        assert "no agent.json" in msg

    def test_valid_agent_json(self, tmp_path):
        (tmp_path / "agent.json").write_text(
            json.dumps({"id": "a", "name": "test"}),
        )
        cfg = _make_config({"a": _profile_ref("a", str(tmp_path))})
        ok, msg = dc.check_agent_json_profiles(cfg)
        assert ok is True

    def test_invalid_json_reported(self, tmp_path):
        (tmp_path / "agent.json").write_text("{bad")
        cfg = _make_config({"a": _profile_ref("a", str(tmp_path))})
        ok, msg = dc.check_agent_json_profiles(cfg)
        assert ok is False
        assert "invalid or unreadable" in msg


# ---------------------------------------------------------------------------
# check_enabled_agents_load_agent_config
# ---------------------------------------------------------------------------


class TestCheckEnabledAgentsLoadAgentConfig:
    def test_no_enabled_agents(self):
        ref = _profile_ref("a", "/nonexistent")
        ref.enabled = False
        cfg = _make_config({"a": ref})
        ok, msg = dc.check_enabled_agents_load_agent_config(cfg)
        assert ok is True
        assert "no enabled agents" in msg

    def test_enabled_missing_agent_json(self, tmp_path):
        cfg = _make_config({"a": _profile_ref("a", str(tmp_path))})
        ok, msg = dc.check_enabled_agents_load_agent_config(cfg)
        assert ok is False
        assert "missing" in msg

    def test_enabled_loads_ok(self, tmp_path, monkeypatch):
        (tmp_path / "agent.json").write_text("{}")
        cfg = _make_config({"a": _profile_ref("a", str(tmp_path))})
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: object())
        ok, msg = dc.check_enabled_agents_load_agent_config(cfg)
        assert ok is True
        assert "load_agent_config OK" in msg

    def test_enabled_load_fails(self, tmp_path, monkeypatch):
        (tmp_path / "agent.json").write_text("{}")
        cfg = _make_config({"a": _profile_ref("a", str(tmp_path))})

        def _boom(aid):
            raise RuntimeError("cannot load")

        monkeypatch.setattr(dc, "load_agent_config", _boom)
        ok, msg = dc.check_enabled_agents_load_agent_config(cfg)
        assert ok is False
        assert "load_agent_config failed" in msg


# ---------------------------------------------------------------------------
# _effective_channels_mcp / enabled_channel_notes
# ---------------------------------------------------------------------------


class TestEffectiveChannelsMcp:
    def test_raw_none_returns_cfg_values(self):
        cfg = _make_config()
        ch, mcp = dc._effective_channels_mcp(cfg, None)
        assert ch is cfg.channels
        assert mcp is cfg.mcp

    def test_raw_channels_override(self):
        cfg = _make_config()
        raw = {"channels": {"discord": {"enabled": True}}}
        ch, mcp = dc._effective_channels_mcp(cfg, raw)
        assert ch.discord.enabled is True
        assert mcp is cfg.mcp

    def test_raw_mcp_override(self):
        cfg = _make_config()
        raw = {"mcp": {"clients": {}}}
        ch, mcp = dc._effective_channels_mcp(cfg, raw)
        assert mcp.clients == {}

    def test_invalid_section_keeps_defaults(self):
        cfg = _make_config()
        raw = {"channels": {"discord": {"enabled": "notabool-obj"}}}
        ch, _ = dc._effective_channels_mcp(cfg, raw)
        # validation of enabled with a bad nested shape may pass or fail;
        # either way the call must not raise.
        assert ch is not None


class TestEnabledChannelNotes:
    def _cfg_with_channels(self, tmp_path, **channel_updates):
        ws = tmp_path / "ws"
        ws.mkdir(exist_ok=True)
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        for name, updates in channel_updates.items():
            sub = getattr(cfg.channels, name)
            for key, value in updates.items():
                setattr(sub, key, value)
        return cfg

    def test_no_notes_when_all_disabled(self, tmp_path):
        cfg = self._cfg_with_channels(tmp_path)
        assert dc.enabled_channel_notes(cfg) == []

    def test_discord_missing_token(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            discord={"enabled": True, "bot_token": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("discord" in n for n in notes)

    def test_telegram_missing_token(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            telegram={"enabled": True, "bot_token": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("telegram" in n for n in notes)

    def test_dingtalk_incomplete(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            dingtalk={"enabled": True, "client_id": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("dingtalk" in n for n in notes)

    def test_feishu_incomplete(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            feishu={"enabled": True, "app_id": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("feishu" in n for n in notes)

    def test_qq_incomplete(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            qq={"enabled": True, "app_id": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("qq" in n for n in notes)

    def test_mattermost_incomplete(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            mattermost={"enabled": True, "url": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("mattermost" in n for n in notes)

    def test_mqtt_empty_host(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            mqtt={"enabled": True, "host": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("mqtt" in n for n in notes)

    def test_matrix_incomplete(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            matrix={"enabled": True, "homeserver": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("matrix" in n for n in notes)

    def test_voice_incomplete(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            voice={"enabled": True, "twilio_account_sid": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("voice" in n for n in notes)

    def test_wecom_incomplete(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            wecom={"enabled": True, "bot_id": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("wecom" in n for n in notes)

    def test_xiaoyi_incomplete(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            xiaoyi={"enabled": True, "ak": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("xiaoyi" in n for n in notes)

    def test_wechat_no_token(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            wechat={"enabled": True, "bot_token": ""},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("wechat" in n and "unset" in n for n in notes)

    def test_wechat_token_ok_no_note(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            wechat={"enabled": True, "bot_token": "tok"},
        )
        assert dc.enabled_channel_notes(cfg) == []

    def test_wechat_token_file_missing(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            wechat={
                "enabled": True,
                "bot_token": "",
                "bot_token_file": str(tmp_path / "nofile"),
            },
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("bot_token_file missing" in n for n in notes)

    def test_wechat_token_file_present(self, tmp_path):
        tok = tmp_path / "tok.txt"
        tok.write_text("x")
        cfg = self._cfg_with_channels(
            tmp_path,
            wechat={
                "enabled": True,
                "bot_token": "",
                "bot_token_file": str(tok),
            },
        )
        assert dc.enabled_channel_notes(cfg) == []

    def test_imessage_missing_db(self, tmp_path):
        cfg = self._cfg_with_channels(
            tmp_path,
            imessage={"enabled": True, "db_path": str(tmp_path / "chat.db")},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("imessage" in n for n in notes)

    def test_console_skipped(self, tmp_path):
        cfg = self._cfg_with_channels(tmp_path, console={"enabled": True})
        assert dc.enabled_channel_notes(cfg) == []

    def test_plugin_channel_enabled_noted(self, tmp_path, monkeypatch):
        from qwenpaw.config.config import ChannelConfig

        ws = tmp_path / "ws"
        ws.mkdir(exist_ok=True)
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        # ChannelConfig allows extra keys (plugin channels).
        cfg.channels = ChannelConfig.model_validate(
            {"myplugin": {"enabled": True}},
        )
        notes = dc.enabled_channel_notes(cfg)
        assert any("myplugin" in n for n in notes)


# ---------------------------------------------------------------------------
# MCP client checks
# ---------------------------------------------------------------------------


class TestMcpClientProblems:
    def _mcp_with_client(self, **client_kwargs):
        from qwenpaw.config.config import MCPClientConfig, MCPConfig

        # model_construct bypasses the transport validator so doctor's
        # own defensive checks (empty command/url) can be exercised.
        defaults = dict(
            name="x",
            description="",
            enabled=True,
            transport="stdio",
            url="",
            headers={},
            command="",
            args=[],
            env={},
            cwd="",
            tools=None,
            oauth=None,
        )
        defaults.update(client_kwargs)
        client = MCPClientConfig.model_construct(**defaults)
        return MCPConfig.model_construct(
            clients={"c": client},
            migration_version=0,
        )

    def test_none_mcp(self):
        assert dc._mcp_client_problems(None, "root") == []

    def test_disabled_skipped(self):
        mcp = self._mcp_with_client(name="x", enabled=False, transport="stdio")
        assert dc._mcp_client_problems(mcp, "root") == []

    def test_stdio_empty_command(self):
        mcp = self._mcp_with_client(
            name="x",
            enabled=True,
            transport="stdio",
            command="",
        )
        problems = dc._mcp_client_problems(mcp, "root")
        assert any("command is empty" in p for p in problems)

    def test_stdio_exe_not_found(self, monkeypatch):
        monkeypatch.setattr(dc.shutil, "which", lambda exe: None)
        mcp = self._mcp_with_client(
            name="x",
            enabled=True,
            transport="stdio",
            command="no-such-exe",
        )
        problems = dc._mcp_client_problems(mcp, "root")
        assert any("not found on PATH" in p for p in problems)

    def test_stdio_exe_found(self, monkeypatch):
        monkeypatch.setattr(dc.shutil, "which", lambda exe: "/usr/bin/x")
        mcp = self._mcp_with_client(
            name="x",
            enabled=True,
            transport="stdio",
            command="python3 -m m",
        )
        assert dc._mcp_client_problems(mcp, "root") == []

    def test_http_empty_url(self):
        mcp = self._mcp_with_client(
            name="x",
            enabled=True,
            transport="streamable_http",
            url="",
        )
        problems = dc._mcp_client_problems(mcp, "root")
        assert any("url is empty" in p for p in problems)

    def test_http_bad_url(self):
        mcp = self._mcp_with_client(
            name="x",
            enabled=True,
            transport="sse",
            url="ftp://x",
        )
        problems = dc._mcp_client_problems(mcp, "root")
        assert any("does not look like" in p for p in problems)

    def test_http_good_url(self):
        mcp = self._mcp_with_client(
            name="x",
            enabled=True,
            transport="streamable_http",
            url="https://example.com/mcp",
        )
        assert dc._mcp_client_problems(mcp, "root") == []


class TestUrlLooksHttpish:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://a.b/c", True),
            ("http://a.b", True),
            ("ftp://a.b", False),
            ("not a url", False),
            ("https://", False),
        ],
    )
    def test_urls(self, url, expected):
        assert dc._url_looks_httpish(url) == expected


class TestMcpClientNotes:
    def test_root_and_agent_mcp(self, tmp_path, monkeypatch):
        from qwenpaw.config.config import MCPClientConfig, MCPConfig

        monkeypatch.setattr(dc.shutil, "which", lambda exe: None)
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "agent.json").write_text(
            json.dumps(
                {
                    "mcp": {
                        "clients": {
                            "ag": {
                                "name": "ag",
                                "enabled": True,
                                "transport": "stdio",
                                "command": "missing-agent-exe",
                            },
                        },
                    },
                },
            ),
        )
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        cfg.mcp = MCPConfig(
            clients={
                "r": MCPClientConfig(
                    name="r",
                    enabled=True,
                    transport="stdio",
                    command="missing-root-exe",
                ),
            },
        )
        notes = dc.mcp_client_notes(cfg)
        assert any("root" in n and "missing-root-exe" in n for n in notes)
        assert any("agent a" in n for n in notes)

    def test_agent_mcp_invalid_skipped(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "agent.json").write_text(
            json.dumps({"mcp": {"clients": "bad"}}),
        )
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        # invalid mcp section is skipped without raising
        notes = dc.mcp_client_notes(cfg)
        assert isinstance(notes, list)


# ---------------------------------------------------------------------------
# skill_layout_notes
# ---------------------------------------------------------------------------


class TestSkillLayoutNotes:
    def test_enabled_skill_missing_dir(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        monkeypatch.setattr(
            dc,
            "read_skill_manifest",
            lambda wd: {"skills": {"s1": {"enabled": True}}},
        )
        monkeypatch.setattr(
            dc,
            "get_workspace_skills_dir",
            lambda wd: wd / "skills",
        )
        notes = dc.skill_layout_notes(cfg)
        assert len(notes) == 1
        assert "s1" in notes[0]

    def test_disabled_skill_ignored(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        monkeypatch.setattr(
            dc,
            "read_skill_manifest",
            lambda wd: {"skills": {"s1": {"enabled": False}}},
        )
        monkeypatch.setattr(
            dc,
            "get_workspace_skills_dir",
            lambda wd: wd / "skills",
        )
        assert dc.skill_layout_notes(cfg) == []

    def test_dir_present_no_note(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        (ws / "skills" / "s1").mkdir(parents=True)
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        monkeypatch.setattr(
            dc,
            "read_skill_manifest",
            lambda wd: {"skills": {"s1": {"enabled": True}}},
        )
        monkeypatch.setattr(
            dc,
            "get_workspace_skills_dir",
            lambda wd: wd / "skills",
        )
        assert dc.skill_layout_notes(cfg) == []

    def test_missing_workspace_skipped(self, tmp_path):
        cfg = _make_config({"a": _profile_ref("a", str(tmp_path / "gone"))})
        assert dc.skill_layout_notes(cfg) == []

    def test_non_dict_skills_ignored(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = _make_config({"a": _profile_ref("a", str(ws))})
        monkeypatch.setattr(
            dc,
            "read_skill_manifest",
            lambda wd: {"skills": ["not", "a", "dict"]},
        )
        assert dc.skill_layout_notes(cfg) == []


# ---------------------------------------------------------------------------
# provider_overview_notes / active_llm_local_failure_hint
# ---------------------------------------------------------------------------


class TestProviderOverviewNotes:
    def test_problems_reported(self, monkeypatch):
        infos = [
            SimpleNamespace(
                id="p1",
                is_custom=True,
                require_api_key=True,
                api_key="",
                is_local=False,
                base_url="",
            ),
            SimpleNamespace(
                id="builtin",
                is_custom=False,
                require_api_key=True,
                api_key="",
                is_local=False,
                base_url="",
            ),
        ]

        class _Mgr:
            async def list_provider_info(self):
                return infos

        class _PM:
            @staticmethod
            def get_instance():
                return _Mgr()

        monkeypatch.setattr(
            "qwenpaw.providers.provider_manager.ProviderManager",
            _PM,
        )
        notes = dc.provider_overview_notes()
        assert len(notes) == 2
        assert any("API key required" in n for n in notes)
        assert any("base_url is empty" in n for n in notes)


class TestActiveLlmLocalFailureHint:
    def test_ollama_with_base_url(self):
        provider = SimpleNamespace(base_url="http://localhost:9999")
        hint = dc.active_llm_local_failure_hint(provider, "ollama")
        assert "ollama serve" in hint
        assert "localhost:9999" in hint

    def test_ollama_default(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        provider = SimpleNamespace(base_url="")
        hint = dc.active_llm_local_failure_hint(provider, "ollama")
        assert "127.0.0.1:11434" in hint

    def test_lmstudio(self):
        provider = SimpleNamespace(base_url="")
        hint = dc.active_llm_local_failure_hint(provider, "lmstudio")
        assert "LM Studio" in hint

    def test_qwenpaw_local(self):
        hint = dc.active_llm_local_failure_hint(
            SimpleNamespace(),
            "qwenpaw-local",
        )
        assert "llama.cpp" in hint

    def test_generic_local(self):
        provider = SimpleNamespace(is_local=True, base_url="http://x:1")
        hint = dc.active_llm_local_failure_hint(provider, "custom-local")
        assert "marked local" in hint

    def test_non_local_empty(self):
        provider = SimpleNamespace(is_local=False)
        assert dc.active_llm_local_failure_hint(provider, "cloud") == ""


# ---------------------------------------------------------------------------
# qwenpaw_local_llm_deep_notes
# ---------------------------------------------------------------------------


class TestQwenpawLocalLlmDeepNotes:
    def _patch_manager(self, monkeypatch, manager):
        monkeypatch.setattr(
            "qwenpaw.local_models.manager.LocalModelManager",
            manager,
        )

    def test_all_ok(self, monkeypatch):
        class _Lm:
            def check_llamacpp_installation(self):
                return True, "found"

            def get_llamacpp_server_status(self):
                return {
                    "running": True,
                    "port": 8080,
                    "model_name": "m",
                    "pid": 1,
                }

            def is_llamacpp_server_transitioning(self):
                return True

        class _Mgr:
            @staticmethod
            def get_instance():
                return _Lm()

        self._patch_manager(monkeypatch, _Mgr)
        notes = dc.qwenpaw_local_llm_deep_notes()
        assert any("binary: OK" in n for n in notes)
        assert any("running=True" in n for n in notes)
        assert any("transitioning" in n for n in notes)

    def test_missing_binary_and_errors(self, monkeypatch):
        class _Lm:
            def check_llamacpp_installation(self):
                return False, ""

            def get_llamacpp_server_status(self):
                raise RuntimeError("no status")

            def is_llamacpp_server_transitioning(self):
                raise RuntimeError("no")

        class _Mgr:
            @staticmethod
            def get_instance():
                return _Lm()

        self._patch_manager(monkeypatch, _Mgr)
        notes = dc.qwenpaw_local_llm_deep_notes()
        assert any("missing or not installed" in n for n in notes)
        assert any("server status failed" in n for n in notes)

    def test_manager_get_instance_fails(self, monkeypatch):
        class _Mgr:
            @staticmethod
            def get_instance():
                raise RuntimeError("boom")

        self._patch_manager(monkeypatch, _Mgr)
        notes = dc.qwenpaw_local_llm_deep_notes()
        assert len(notes) == 1
        assert "LocalModelManager" in notes[0]

    def test_install_check_exception(self, monkeypatch):
        class _Lm:
            def check_llamacpp_installation(self):
                raise RuntimeError("check exploded")

            def get_llamacpp_server_status(self):
                return {}

        class _Mgr:
            @staticmethod
            def get_instance():
                return _Lm()

        self._patch_manager(monkeypatch, _Mgr)
        notes = dc.qwenpaw_local_llm_deep_notes()
        assert any("install check failed" in n for n in notes)


# ---------------------------------------------------------------------------
# model slot resolution / connection checks
# ---------------------------------------------------------------------------


class TestResolveAgentEffectiveModelSlot:
    def _agent_cfg(self, active_model=None, routing=None):
        return SimpleNamespace(active_model=active_model, llm_routing=routing)

    def test_active_model_wins(self):
        slot = SimpleNamespace(provider_id="p", model="m")
        routing = SimpleNamespace(enabled=True, mode="local_first")
        slot2, source = dc._resolve_agent_effective_model_slot(
            self._agent_cfg(active_model=slot, routing=routing),
            None,
        )
        assert slot2 is slot
        assert source == "agent.active_model"

    def test_routing_cloud_first_uses_cloud(self):
        cloud = SimpleNamespace(provider_id="p", model="m")
        routing = SimpleNamespace(
            enabled=True,
            mode="cloud_first",
            cloud=cloud,
        )
        slot, source = dc._resolve_agent_effective_model_slot(
            self._agent_cfg(routing=routing),
            None,
        )
        assert slot is cloud

    def test_routing_cloud_first_falls_back_to_active(self):
        active = SimpleNamespace(provider_id="p", model="m")
        routing = SimpleNamespace(enabled=True, mode="cloud_first", cloud=None)
        slot, source = dc._resolve_agent_effective_model_slot(
            self._agent_cfg(routing=routing),
            active,
        )
        assert slot is active
        assert "cloud fallback" in source

    def test_routing_cloud_first_nothing(self):
        routing = SimpleNamespace(enabled=True, mode="cloud_first", cloud=None)
        slot, source = dc._resolve_agent_effective_model_slot(
            self._agent_cfg(routing=routing),
            None,
        )
        assert slot is None

    def test_routing_local_first(self):
        local = SimpleNamespace(provider_id="p", model="m")
        routing = SimpleNamespace(
            enabled=True,
            mode="local_first",
            local=local,
        )
        slot, _ = dc._resolve_agent_effective_model_slot(
            self._agent_cfg(routing=routing),
            None,
        )
        assert slot is local

    def test_routing_local_first_unset(self):
        routing = SimpleNamespace(enabled=True, mode="local_first", local=None)
        slot, source = dc._resolve_agent_effective_model_slot(
            self._agent_cfg(routing=routing),
            None,
        )
        assert slot is None
        assert "local slot is not set" in source

    def test_no_routing_uses_active(self):
        active = SimpleNamespace(provider_id="p", model="m")
        routing = SimpleNamespace(enabled=False)
        slot, source = dc._resolve_agent_effective_model_slot(
            self._agent_cfg(routing=routing),
            active,
        )
        assert slot is active
        assert source == "providers.active_llm"

    def test_nothing_anywhere(self):
        routing = SimpleNamespace(enabled=False)
        slot, source = dc._resolve_agent_effective_model_slot(
            self._agent_cfg(routing=routing),
            None,
        )
        assert slot is None

    def test_slot_is_set(self):
        assert dc._slot_is_set(None) is False
        assert (
            dc._slot_is_set(SimpleNamespace(provider_id="", model="m"))
            is False
        )
        assert (
            dc._slot_is_set(
                SimpleNamespace(provider_id="p", model="m"),
            )
            is True
        )


class TestCheckEnabledAgentsModelConnections:
    def _patch_pm(self, monkeypatch, mgr):
        class _PM:
            @staticmethod
            def get_instance():
                return mgr

        monkeypatch.setattr(
            "qwenpaw.providers.provider_manager.ProviderManager",
            _PM,
        )

    def test_no_enabled_agents(self, monkeypatch):
        class _Mgr:
            def get_active_model(self):
                return None

        self._patch_pm(monkeypatch, _Mgr())
        cfg = _make_config({})
        ok, lines, notes = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is True
        assert lines == ["(no enabled agents)"]

    def test_load_agent_config_fails(self, monkeypatch):
        class _Mgr:
            def get_active_model(self):
                return None

        self._patch_pm(monkeypatch, _Mgr())
        monkeypatch.setattr(
            dc,
            "load_agent_config",
            lambda aid: (_ for _ in ()).throw(RuntimeError("no")),
        )
        ref = _profile_ref("a", "/x")
        cfg = _make_config({"a": ref})
        ok, lines, _ = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is False
        assert any("load_agent_config failed" in line for line in lines)

    def test_no_model_resolved(self, monkeypatch):
        class _Mgr:
            def get_active_model(self):
                return None

        self._patch_pm(monkeypatch, _Mgr())
        agent_cfg = SimpleNamespace(
            active_model=None,
            llm_routing=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: agent_cfg)
        cfg = _make_config({"a": _profile_ref("a", "/x")})
        ok, lines, _ = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is False
        assert any("no model resolved" in line for line in lines)

    def test_provider_not_found(self, monkeypatch):
        class _Mgr:
            def get_active_model(self):
                return SimpleNamespace(provider_id="ghost", model="m")

            def get_provider(self, pid):
                return None

        self._patch_pm(monkeypatch, _Mgr())
        agent_cfg = SimpleNamespace(
            active_model=None,
            llm_routing=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: agent_cfg)
        cfg = _make_config({"a": _profile_ref("a", "/x")})
        ok, lines, _ = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is False
        assert any("provider not found" in line for line in lines)

    def test_cloud_provider_missing_base_url(self, monkeypatch):
        provider = SimpleNamespace(
            is_local=False,
            base_url="",
            require_api_key=False,
        )

        class _Mgr:
            def get_active_model(self):
                return SimpleNamespace(provider_id="p", model="m")

            def get_provider(self, pid):
                return provider

        self._patch_pm(monkeypatch, _Mgr())
        agent_cfg = SimpleNamespace(
            active_model=None,
            llm_routing=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: agent_cfg)
        cfg = _make_config({"a": _profile_ref("a", "/x")})
        ok, lines, _ = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is False
        assert any("base_url is not set" in line for line in lines)

    def test_missing_api_key(self, monkeypatch):
        provider = SimpleNamespace(
            is_local=False,
            base_url="http://x",
            require_api_key=True,
            api_key="",
        )

        class _Mgr:
            def get_active_model(self):
                return SimpleNamespace(provider_id="p", model="m")

            def get_provider(self, pid):
                return provider

        self._patch_pm(monkeypatch, _Mgr())
        agent_cfg = SimpleNamespace(
            active_model=None,
            llm_routing=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: agent_cfg)
        cfg = _make_config({"a": _profile_ref("a", "/x")})
        ok, lines, _ = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is False
        assert any("API key is required" in line for line in lines)

    def test_connection_ok(self, monkeypatch):
        class _Provider:
            is_local = False
            base_url = "http://x"
            require_api_key = False
            support_connection_check = True

            async def check_model_connection(self, model, timeout=None):
                return True, ""

        class _Mgr:
            def get_active_model(self):
                return SimpleNamespace(provider_id="p", model="m")

            def get_provider(self, pid):
                return _Provider()

        self._patch_pm(monkeypatch, _Mgr())
        agent_cfg = SimpleNamespace(
            active_model=None,
            llm_routing=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: agent_cfg)
        cfg = _make_config({"a": _profile_ref("a", "/x")})
        ok, lines, _ = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is True
        assert any("reachable" in line for line in lines)

    def test_check_skipped_for_provider(self, monkeypatch):
        class _Provider:
            is_local = False
            base_url = "http://x"
            require_api_key = False
            support_connection_check = False

        class _Mgr:
            def get_active_model(self):
                return SimpleNamespace(provider_id="p", model="m")

            def get_provider(self, pid):
                return _Provider()

        self._patch_pm(monkeypatch, _Mgr())
        agent_cfg = SimpleNamespace(
            active_model=None,
            llm_routing=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: agent_cfg)
        cfg = _make_config({"a": _profile_ref("a", "/x")})
        ok, lines, _ = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is True
        assert any("live check skipped" in line for line in lines)

    def test_connection_fails_local_hint(self, monkeypatch):
        class _Provider:
            is_local = True
            base_url = "http://127.0.0.1:11434"
            require_api_key = False
            support_connection_check = True

            async def check_model_connection(self, model, timeout=None):
                return False, "connection refused"

        class _Mgr:
            def get_active_model(self):
                return SimpleNamespace(provider_id="ollama", model="m")

            def get_provider(self, pid):
                return _Provider()

        self._patch_pm(monkeypatch, _Mgr())
        agent_cfg = SimpleNamespace(
            active_model=None,
            llm_routing=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: agent_cfg)
        cfg = _make_config({"a": _profile_ref("a", "/x")})
        ok, lines, _ = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is False
        assert any("unreachable" in line for line in lines)
        assert any("ollama serve" in line for line in lines)

    def test_check_exception_treated_as_failure(self, monkeypatch):
        class _Provider:
            is_local = False
            base_url = "http://x"
            require_api_key = False
            support_connection_check = True

            async def check_model_connection(self, model, timeout=None):
                raise RuntimeError("boom")

        class _Mgr:
            def get_active_model(self):
                return SimpleNamespace(provider_id="p", model="m")

            def get_provider(self, pid):
                return _Provider()

        self._patch_pm(monkeypatch, _Mgr())
        agent_cfg = SimpleNamespace(
            active_model=None,
            llm_routing=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: agent_cfg)
        cfg = _make_config({"a": _profile_ref("a", "/x")})
        ok, lines, _ = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=False,
            ),
        )
        assert ok is False
        assert any("boom" in line for line in lines)

    def test_deep_local_provider_adds_notes(self, monkeypatch):
        class _Provider:
            is_local = True
            base_url = "http://127.0.0.1:8080"
            require_api_key = False
            support_connection_check = True

            async def check_model_connection(self, model, timeout=None):
                return True, ""

        class _Mgr:
            def get_active_model(self):
                return SimpleNamespace(provider_id="qwenpaw-local", model="m")

            def get_provider(self, pid):
                return _Provider()

        self._patch_pm(monkeypatch, _Mgr())
        agent_cfg = SimpleNamespace(
            active_model=None,
            llm_routing=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(dc, "load_agent_config", lambda aid: agent_cfg)
        monkeypatch.setattr(
            dc,
            "qwenpaw_local_llm_deep_notes",
            lambda: ["llama.cpp binary: OK"],
        )
        cfg = _make_config({"a": _profile_ref("a", "/x")})
        ok, lines, notes = asyncio.run(
            dc.check_enabled_agents_model_connections(
                cfg,
                timeout=1.0,
                deep=True,
            ),
        )
        assert ok is True
        assert notes == ["llama.cpp binary: OK"]


# ---------------------------------------------------------------------------
# console_static_diagnostic_notes / api_target_mismatch_note
# ---------------------------------------------------------------------------


class TestConsoleStaticDiagnosticNotes:
    def test_index_present_and_repo(self, tmp_path, monkeypatch):
        monkeypatch.delenv("QWENPAW_CONSOLE_STATIC_DIR", raising=False)
        static = tmp_path / "static"
        static.mkdir()
        (static / "index.html").write_text("<html>")
        monkeypatch.setattr(
            "qwenpaw.utils.console_static.resolve_console_static_dir",
            lambda: str(static),
        )
        monkeypatch.setattr(
            "qwenpaw.utils.console_static.find_qwenpaw_source_repo_root",
            lambda: tmp_path,
        )
        notes = dc.console_static_diagnostic_notes()
        joined = "\n".join(notes)
        assert "index.html present" in joined
        assert "source checkout detected" in joined
        assert "npm on PATH:" in joined

    def test_index_missing_no_repo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("QWENPAW_CONSOLE_STATIC_DIR", "/custom/static")
        static = tmp_path / "static"
        static.mkdir()
        monkeypatch.setattr(
            "qwenpaw.utils.console_static.resolve_console_static_dir",
            lambda: str(static),
        )
        monkeypatch.setattr(
            "qwenpaw.utils.console_static.find_qwenpaw_source_repo_root",
            lambda: None,
        )
        notes = dc.console_static_diagnostic_notes()
        joined = "\n".join(notes)
        assert "QWENPAW_CONSOLE_STATIC_DIR" in joined
        assert "index.html missing" in joined
        assert "wheel installs" in joined


class TestApiTargetMismatchNote:
    def _cfg(self, host, port):
        return SimpleNamespace(last_api=SimpleNamespace(host=host, port=port))

    def test_no_last_api(self):
        assert (
            dc.api_target_mismatch_note(self._cfg(None, None), "http://x")
            is None
        )

    def test_match(self):
        assert (
            dc.api_target_mismatch_note(
                self._cfg("127.0.0.1", 8088),
                "http://127.0.0.1:8088",
            )
            is None
        )

    def test_defaults_applied(self):
        assert (
            dc.api_target_mismatch_note(
                self._cfg(None, None),
                "http://127.0.0.1:8088",
            )
            is None
        )

    def test_mismatch(self):
        note = dc.api_target_mismatch_note(
            self._cfg("0.0.0.0", 9999),
            "http://127.0.0.1:8088",
        )
        assert note is not None
        assert "CLI targets" in note

# -*- coding: utf-8 -*-
"""Unit tests for cli/doctor_cmd.py.

Covers the small read-only helpers (classification, health probe, python
mismatch note, web-auth check, console-root response) plus the two CLI
entry points ``doctor`` (``run_doctor_checks``) and ``doctor fix``
(``_run_doctor_fix_cli``). Every collaborator imported into the
``doctor_cmd`` namespace is monkeypatched so the whole flow runs
in-process with no network or disk access to real state.
"""
# pylint: disable=protected-access,too-many-public-methods,unnecessary-lambda,unused-argument,unused-import,unused-variable  # noqa: E501
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import click
import httpx
import pytest
from click.testing import CliRunner

import qwenpaw.cli.doctor_cmd as dc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _Resp:
    """Minimal httpx.Response-like object for classification tests."""

    def __init__(
        self,
        status_code=200,
        headers=None,
        text="",
        json_body=None,
        raise_json=False,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._json = json_body
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise json.JSONDecodeError("bad", "doc", 0)
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


def _ctx(host="127.0.0.1", port=8088):
    return SimpleNamespace(obj={"host": host, "port": port})


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------


class TestDoctorFixHint:
    def test_prints_to_stderr(self, capsys):
        dc._doctor_fix_hint("do the thing")
        assert "Hint: do the thing" in capsys.readouterr().err


class TestIsConsoleStaticPositiveNote:
    def test_resolved_static_dir_ok_when_index_present(self):
        line = "resolved static dir: /x (index.html present)"
        assert dc._is_console_static_positive_note(line) is True

    def test_resolved_static_dir_bad_when_missing(self):
        line = "resolved static dir: /x (no index)"
        assert dc._is_console_static_positive_note(line) is False

    def test_npm_on_path_found(self):
        assert (
            dc._is_console_static_positive_note("npm on PATH: /usr/bin/npm")
            is True
        )

    def test_npm_on_path_not_found(self):
        assert (
            dc._is_console_static_positive_note("npm on PATH: not found")
            is False
        )

    def test_other_line(self):
        assert dc._is_console_static_positive_note("something else") is False


class TestSamePythonExecutable:
    def test_same_file(self, tmp_path):
        a = tmp_path / "py"
        a.write_text("")
        assert dc._same_python_executable(str(a), str(a)) is True

    def test_resolve_fallback_when_samefile_raises(self, tmp_path):
        # nonexistent paths -> os.path.samefile raises OSError -> resolve()
        a = tmp_path / "nope1"
        b = tmp_path / "nope2"
        assert dc._same_python_executable(str(a), str(b)) is False
        assert dc._same_python_executable(str(a), str(a)) is True


class TestHttpGet:
    def test_sets_trust_env_default(self, monkeypatch):
        seen = {}

        def fake_get(url, **kw):
            seen.update(kw)
            return _Resp()

        monkeypatch.setattr(dc.httpx, "get", fake_get)
        monkeypatch.setattr(dc, "trust_env_for_url", lambda u: False)
        dc._http_get("http://x/api")
        assert seen["trust_env"] is False

    def test_explicit_trust_env_not_overridden(self, monkeypatch):
        seen = {}

        def fake_get(url, **kw):
            seen.update(kw)
            return _Resp()

        monkeypatch.setattr(dc.httpx, "get", fake_get)
        dc._http_get("http://x/api", trust_env=True)
        assert seen["trust_env"] is True


class TestProviderIsConfigured:
    def test_local(self):
        p = SimpleNamespace(
            is_local=True,
            base_url="",
            require_api_key=True,
            api_key="",
        )
        assert dc._provider_is_configured(p) == (True, "")

    def test_missing_base_url(self):
        p = SimpleNamespace(
            is_local=False,
            base_url="  ",
            require_api_key=False,
            api_key="",
        )
        ok, why = dc._provider_is_configured(p)
        assert ok is False
        assert "base_url" in why

    def test_missing_api_key(self):
        p = SimpleNamespace(
            is_local=False,
            base_url="http://x",
            require_api_key=True,
            api_key=" ",
        )
        ok, why = dc._provider_is_configured(p)
        assert ok is False
        assert "API key" in why

    def test_ok(self):
        p = SimpleNamespace(
            is_local=False,
            base_url="http://x",
            require_api_key=True,
            api_key="k",
        )
        assert dc._provider_is_configured(p) == (True, "")


class TestCheckWorkingDir:
    def test_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(dc, "WORKING_DIR", tmp_path / "gone")
        ok, detail = dc._check_working_dir()
        assert ok is False
        assert "missing" in detail

    def test_not_writable(self, monkeypatch, tmp_path):
        d = tmp_path / "wd"
        d.mkdir()
        monkeypatch.setattr(dc, "WORKING_DIR", d)
        monkeypatch.setattr(dc.os, "access", lambda p, m: False)
        ok, detail = dc._check_working_dir()
        assert ok is False
        assert "not writable" in detail

    def test_ok(self, monkeypatch, tmp_path):
        d = tmp_path / "wd"
        d.mkdir()
        monkeypatch.setattr(dc, "WORKING_DIR", d)
        ok, detail = dc._check_working_dir()
        assert ok is True
        assert detail == str(d)


class TestCheckConsoleStaticFiles:
    def test_present(self, monkeypatch, tmp_path):
        d = tmp_path / "static"
        d.mkdir()
        (d / "index.html").write_text("<html>")
        monkeypatch.setattr(dc, "resolve_console_static_dir", lambda: str(d))
        ok, detail = dc._check_console_static_files()
        assert ok is True
        assert detail == str(d)

    def test_missing(self, monkeypatch, tmp_path):
        d = tmp_path / "static"
        d.mkdir()
        monkeypatch.setattr(dc, "resolve_console_static_dir", lambda: str(d))
        ok, detail = dc._check_console_static_files()
        assert ok is False
        assert "index.html missing" in detail


class TestCheckWebAuth:
    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(dc, "is_auth_enabled", lambda: False)
        ok, detail = dc._check_web_auth("http://x")
        assert ok is True
        assert "disabled" in detail

    def test_enabled_no_user(self, monkeypatch):
        monkeypatch.setattr(dc, "is_auth_enabled", lambda: True)
        monkeypatch.setattr(dc, "has_registered_users", lambda: False)
        ok, detail = dc._check_web_auth("http://x")
        assert ok is False
        assert "no account registered" in detail

    def test_enabled_with_user(self, monkeypatch):
        monkeypatch.setattr(dc, "is_auth_enabled", lambda: True)
        monkeypatch.setattr(dc, "has_registered_users", lambda: True)
        ok, detail = dc._check_web_auth("http://x")
        assert ok is True
        assert "sign in" in detail


class TestClassifyConsoleRootResponse:
    def test_html_content_type(self):
        r = _Resp(headers={"content-type": "text/html"})
        ok, detail = dc._classify_console_root_response(r)
        assert ok is True
        assert "returns HTML" in detail

    def test_doctype_body(self):
        r = _Resp(headers={}, text="<!DOCTYPE html><html></html>")
        ok, _ = dc._classify_console_root_response(r)
        assert ok is True

    def test_html_tag_body(self):
        r = _Resp(headers={}, text="<html><body></body></html>")
        ok, _ = dc._classify_console_root_response(r)
        assert ok is True

    def test_json_console_not_available(self):
        r = _Resp(
            headers={"content-type": "application/json"},
            json_body={"message": "Web Console is not available"},
        )
        ok, detail = dc._classify_console_root_response(r)
        assert ok is False
        assert "console bundle is not installed" in detail

    def test_json_other(self):
        r = _Resp(
            headers={"content-type": "application/json"},
            json_body={"message": "something"},
        )
        ok, detail = dc._classify_console_root_response(r)
        assert ok is False
        assert "JSON instead of the console page" in detail

    def test_json_unparseable(self):
        r = _Resp(
            headers={"content-type": "application/json"},
            text="{",
            raise_json=True,
        )
        ok, detail = dc._classify_console_root_response(r)
        assert ok is False
        assert "not parseable" in detail

    def test_json_startswith_brace_but_bad_ct(self):
        r = _Resp(headers={}, text='{"message": "x"}')
        ok, detail = dc._classify_console_root_response(r)
        assert ok is False

    def test_unknown_content_type(self):
        r = _Resp(headers={"content-type": "image/png"}, text="binary")
        ok, detail = dc._classify_console_root_response(r)
        assert ok is False
        assert "unexpected GET / response" in detail


class TestServerPythonMismatchNote:
    def test_no_server_env(self):
        assert (
            dc._doctor_server_python_mismatch_note("a", "envA", None, None)
            is None
        )

    def test_same_executable(self, tmp_path):
        exe = tmp_path / "py"
        exe.write_text("")
        assert (
            dc._doctor_server_python_mismatch_note(
                str(exe),
                "env",
                "env",
                str(exe),
            )
            is None
        )

    def test_different_executable(self, tmp_path):
        a = tmp_path / "pya"
        b = tmp_path / "pyb"
        a.write_text("")
        b.write_text("")
        note = dc._doctor_server_python_mismatch_note(
            str(a),
            "env",
            "env",
            str(b),
        )
        assert note is not None
        assert "not using the same Python" in note

    def test_env_label_differs(self):
        note = dc._doctor_server_python_mismatch_note(
            "/x/py",
            "venvA",
            "venvB",
            None,
        )
        assert note is not None
        assert "environment label differs" in note

    def test_env_label_matches(self):
        assert (
            dc._doctor_server_python_mismatch_note(
                "/x/py",
                "venv",
                "venv",
                None,
            )
            is None
        )


# ---------------------------------------------------------------------------
# _check_api_health / _fetch_running_server_python
# ---------------------------------------------------------------------------


class TestCheckApiHealth:
    def test_request_error(self, monkeypatch, capsys):
        def boom(url, **kw):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(dc, "_http_get", boom)
        ok, resp = dc._check_api_health("http://x", 1.0)
        assert ok is False
        assert resp is None
        assert "health not reachable" in capsys.readouterr().err

    def test_200(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get", lambda u, **kw: _Resp(200))
        ok, resp = dc._check_api_health("http://x", 1.0)
        assert ok is True
        assert resp.status_code == 200

    def test_503_with_detail(self, monkeypatch, capsys):
        monkeypatch.setattr(
            dc,
            "_http_get",
            lambda u, **kw: _Resp(503, json_body={"detail": "booting"}),
        )
        ok, resp = dc._check_api_health("http://x", 1.0)
        assert ok is False
        assert "booting" in capsys.readouterr().err

    def test_503_no_body(self, monkeypatch, capsys):
        monkeypatch.setattr(
            dc,
            "_http_get",
            lambda u, **kw: _Resp(503, raise_json=True, text="x"),
        )
        ok, resp = dc._check_api_health("http://x", 1.0)
        assert ok is False
        assert "Background startup in progress" in capsys.readouterr().err

    def test_other_status(self, monkeypatch, capsys):
        monkeypatch.setattr(dc, "_http_get", lambda u, **kw: _Resp(404))
        ok, resp = dc._check_api_health("http://x", 1.0)
        assert ok is False
        assert "HTTP 404" in capsys.readouterr().err


class TestFetchRunningServerPython:
    def test_request_error(self, monkeypatch):
        def boom(url, **kw):
            raise httpx.ConnectError("nope")

        monkeypatch.setattr(dc, "_http_get", boom)
        env, exe, note = dc._fetch_running_server_python("http://x", 1.0)
        assert env is None
        assert exe is None
        assert "not available" in note

    def test_200_with_env(self, monkeypatch):
        monkeypatch.setattr(
            dc,
            "_http_get",
            lambda u, **kw: _Resp(
                200,
                json_body={
                    "python_environment": "venvX",
                    "python_executable": "/p",
                },
            ),
        )
        env, exe, note = dc._fetch_running_server_python("http://x", 1.0)
        assert env == "venvX"
        assert exe == "/p"
        assert note is None

    def test_200_no_env_field(self, monkeypatch):
        monkeypatch.setattr(
            dc,
            "_http_get",
            lambda u, **kw: _Resp(200, json_body={"python_executable": "/p"}),
        )
        env, exe, note = dc._fetch_running_server_python("http://x", 1.0)
        assert env is None
        assert "did not report" in note

    def test_200_non_dict_body(self, monkeypatch):
        monkeypatch.setattr(
            dc,
            "_http_get",
            lambda u, **kw: _Resp(200, json_body=["a"]),
        )
        env, exe, note = dc._fetch_running_server_python("http://x", 1.0)
        assert env is None
        assert "unexpected payload" in note

    def test_200_not_json(self, monkeypatch):
        monkeypatch.setattr(
            dc,
            "_http_get",
            lambda u, **kw: _Resp(200, raise_json=True, text="x"),
        )
        env, exe, note = dc._fetch_running_server_python("http://x", 1.0)
        assert env is None
        assert "not JSON" in note

    def test_auth_required(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get", lambda u, **kw: _Resp(401))
        env, exe, note = dc._fetch_running_server_python("http://x", 1.0)
        assert env is None
        assert "requires authentication" in note

    def test_other_status(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get", lambda u, **kw: _Resp(500))
        env, exe, note = dc._fetch_running_server_python("http://x", 1.0)
        assert env is None
        assert "HTTP 500" in note


# ---------------------------------------------------------------------------
# _check_active_llm
# ---------------------------------------------------------------------------


class _Slot:
    def __init__(self, provider_id, model):
        self.provider_id = provider_id
        self.model = model


class _Mgr:
    def __init__(self, slot=None, provider=None):
        self._slot = slot
        self._provider = provider

    def get_active_model(self):
        return self._slot

    def get_provider(self, pid):
        return self._provider


class TestCheckActiveLlm:
    def test_no_slot(self, monkeypatch):
        monkeypatch.setattr(
            dc.ProviderManager,
            "get_instance",
            staticmethod(lambda: _Mgr(None)),
        )
        ok, detail, notes = _run_async(dc._check_active_llm(1.0, False))
        assert ok is False
        assert "no active LLM slot" in detail

    def test_provider_missing(self, monkeypatch):
        monkeypatch.setattr(
            dc.ProviderManager,
            "get_instance",
            staticmethod(lambda: _Mgr(_Slot("p", "m"), None)),
        )
        ok, detail, notes = _run_async(dc._check_active_llm(1.0, False))
        assert ok is False
        assert "provider not found" in detail

    def test_provider_not_configured(self, monkeypatch):
        prov = SimpleNamespace(
            is_local=False,
            base_url="",
            require_api_key=False,
            api_key="",
        )
        monkeypatch.setattr(
            dc.ProviderManager,
            "get_instance",
            staticmethod(lambda: _Mgr(_Slot("p", "m"), prov)),
        )
        ok, detail, notes = _run_async(dc._check_active_llm(1.0, False))
        assert ok is False
        assert "base_url" in detail

    def test_skip_connection_check(self, monkeypatch):
        prov = SimpleNamespace(
            is_local=False,
            base_url="http://x",
            require_api_key=False,
            api_key="",
            support_connection_check=False,
        )
        monkeypatch.setattr(
            dc.ProviderManager,
            "get_instance",
            staticmethod(lambda: _Mgr(_Slot("p", "m"), prov)),
        )
        ok, detail, notes = _run_async(dc._check_active_llm(1.0, False))
        assert ok is True
        assert "live check skipped" in detail

    def test_ping_success(self, monkeypatch):
        async def check(model_id, timeout=5):
            return True, "up"

        prov = SimpleNamespace(
            is_local=False,
            base_url="http://x",
            require_api_key=False,
            api_key="",
            check_model_connection=check,
        )
        monkeypatch.setattr(
            dc.ProviderManager,
            "get_instance",
            staticmethod(lambda: _Mgr(_Slot("p", "m"), prov)),
        )
        ok, detail, notes = _run_async(dc._check_active_llm(1.0, False))
        assert ok is True
        assert "reachable" in detail

    def test_ping_failure_local_hint(self, monkeypatch):
        async def check(model_id, timeout=5):
            return False, "down"

        prov = SimpleNamespace(
            is_local=True,
            base_url="",
            require_api_key=False,
            api_key="",
            check_model_connection=check,
        )
        monkeypatch.setattr(
            dc.ProviderManager,
            "get_instance",
            staticmethod(lambda: _Mgr(_Slot("qwenpaw-local", "m"), prov)),
        )
        monkeypatch.setattr(
            dc,
            "active_llm_local_failure_hint",
            lambda provider, pid: "start the server",
        )
        monkeypatch.setattr(
            dc,
            "qwenpaw_local_llm_deep_notes",
            lambda: ["deep note"],
        )
        ok, detail, notes = _run_async(dc._check_active_llm(1.0, True))
        assert ok is False
        assert "start the server" in detail
        assert notes == ["deep note"]


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCliApiHostPortFromCtx:
    def test_reads_obj_dict(self):
        root = click.Context(click.Command("cli"))
        root.obj = {"host": "1.2.3.4", "port": 1234}
        child = click.Context(click.Command("doctor"), parent=root)
        host, port = dc._cli_api_host_port_from_ctx(child)
        assert (host, port) == ("1.2.3.4", 1234)

    def test_obj_not_dict(self):
        root = click.Context(click.Command("cli"))
        root.obj = object()
        child = click.Context(click.Command("doctor"), parent=root)
        host, port = dc._cli_api_host_port_from_ctx(child)
        assert (host, port) == (None, None)


class TestRunDoctorFixCli:
    def test_delegates_and_exits_on_error(self, monkeypatch):
        captured = {}

        def fake_run(**kw):
            captured.update(kw)
            return 2

        import qwenpaw.cli.doctor_fix_runner as dfr

        monkeypatch.setattr(dfr, "run_doctor_fix", fake_run)
        root = click.Context(click.Command("cli"))
        root.obj = {"host": "h", "port": 1}
        ctx = click.Context(click.Command("fix"), parent=root)
        with pytest.raises(SystemExit) as exc:
            dc._run_doctor_fix_cli(
                ctx,
                dry_run=True,
                yes=False,
                non_interactive=False,
                only="a,b",
                no_backup=True,
                backup_dir=None,
            )
        assert exc.value.code == 2
        assert captured["cli_api_host"] == "h"
        assert captured["cli_api_port"] == 1

    def test_returns_normally_on_zero(self, monkeypatch):
        import qwenpaw.cli.doctor_fix_runner as dfr

        monkeypatch.setattr(dfr, "run_doctor_fix", lambda **kw: 0)
        root = click.Context(click.Command("cli"))
        root.obj = {}
        ctx = click.Context(click.Command("fix"), parent=root)
        # should not raise
        dc._run_doctor_fix_cli(
            ctx,
            dry_run=False,
            yes=True,
            non_interactive=False,
            only=None,
            no_backup=False,
            backup_dir=None,
        )

    def test_echo_err_and_echo_passed_to_runner(
        self,
        monkeypatch,
        capsys,
    ):
        import qwenpaw.cli.doctor_fix_runner as dfr

        def fake_run(**kw):
            kw["echo"]("out line")
            kw["echo_err"]("err line")
            return 0

        monkeypatch.setattr(dfr, "run_doctor_fix", fake_run)
        root = click.Context(click.Command("cli"))
        root.obj = {}
        ctx = click.Context(click.Command("fix"), parent=root)
        dc._run_doctor_fix_cli(
            ctx,
            dry_run=False,
            yes=True,
            non_interactive=False,
            only=None,
            no_backup=False,
            backup_dir=None,
        )
        combined = capsys.readouterr()
        assert "out line" in combined.out
        assert "err line" in combined.err


# ---------------------------------------------------------------------------
# run_doctor_checks (full pipeline)
# ---------------------------------------------------------------------------


class _OkPatch:
    """Context manager that stubs every collaborator to a passing state.

    Individual values can be overridden via keyword arguments so tests can
    flip a single check to FAIL and assert the exit / hint behaviour.
    """

    def __init__(self, monkeypatch, **overrides):
        self.mp = monkeypatch
        self.ov = overrides

    def __enter__(self):
        mp, ov = self.mp, self.ov
        defaults = {
            "_fetch_running_server_python": lambda base, t: (
                "srv-env",
                None,
                None,
            ),
            "environment_summary_lines": lambda **kw: ["env line"],
            "summarize_python_environment": lambda: "doctor-env",
            "windows_environment_lines": lambda: [],
            "strict_validate_config_file": lambda: (True, "config ok"),
            "load_raw_config_dict": lambda: {},
            "scan_unknown_config_keys": lambda raw: [],
            "load_config": lambda: SimpleNamespace(),
            "legacy_single_agent_workspace_note": lambda cfg: None,
            "check_agent_profile_workspaces": lambda cfg: (True, "ws ok"),
            "check_agent_json_profiles": lambda cfg: (True, "aj ok"),
            "check_enabled_agents_load_agent_config": lambda cfg: (
                True,
                "acl ok",
            ),
            "enabled_channel_notes": lambda cfg: [],
            "run_extension_contributions": lambda ctx: [],
            "collect_deep_channel_connectivity_notes": lambda cfg, t: [],
            "mcp_client_notes": lambda cfg: [],
            "skill_layout_notes": lambda cfg: [],
            "security_baseline_notes": lambda cfg: [],
            "memory_embedding_notes": lambda cfg: [],
            "workspace_hygiene_notes": lambda cfg: [],
            "check_cron_jobs_files": lambda cfg: (True, "cron ok"),
            "_check_working_dir": lambda: (True, str(ov.get("_wd", "/wd"))),
            "check_app_log_writable": lambda: (True, "log ok"),
            "check_browser_readiness": lambda cfg: (True, "browser ok"),
            "check_agent_workspace_writable": lambda cfg: (True, "ws-w ok"),
            "startup_extra_volume_disk_notes": lambda cfg: [],
            "_check_console_static_files": lambda: (True, "static ok"),
            "console_static_diagnostic_notes": lambda: [
                "resolved static dir: /x (index.html present)",
            ],
            "_check_web_auth": lambda base: (True, "auth ok"),
            "provider_overview_notes": lambda: [],
            "_check_active_llm": _async(lambda t, d: (True, "llm ok", [])),
            "check_enabled_agents_model_connections": _async(
                lambda cfg, timeout, deep: (True, [], []),
            ),
            "api_target_mismatch_note": lambda cfg, base: None,
            "_check_api_health": lambda base, t: (True, _Resp(200)),
            "_http_get": lambda url, **kw: _Resp(
                200,
                headers={"content-type": "text/html"},
            ),
            "_classify_console_root_response": lambda resp: (True, "html ok"),
            "_doctor_server_python_mismatch_note": lambda *a, **kw: None,
            "__version__": "9.9.9",
        }
        defaults.update(ov)
        for name, val in defaults.items():
            mp.setattr(dc, name, val)
        return self

    def __exit__(self, *exc):
        return False


def _async(fn):
    async def wrapper(*a, **kw):
        return fn(*a, **kw)

    return wrapper


class TestRunDoctorChecks:
    def test_all_ok_no_exit(self, monkeypatch, capsys):
        with _OkPatch(monkeypatch):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        out = capsys.readouterr().out
        assert "=== Environment ===" in out
        assert "=== Config ===" in out
        assert "=== Active LLM ===" in out
        assert "=== API ===" in out

    def test_config_invalid_exits_and_skips_sections(
        self,
        monkeypatch,
        capsys,
    ):
        with _OkPatch(
            monkeypatch,
            strict_validate_config_file=lambda: (False, "config broken"),
        ):
            with pytest.raises(SystemExit) as exc:
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert exc.value.code == 1
        combined = capsys.readouterr()
        assert "config broken" in combined.err
        assert "Skipped (root config invalid)" in combined.out

    def test_workspace_fail_exits_with_hint(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            check_agent_profile_workspaces=lambda cfg: (False, "ws bad"),
        ):
            with pytest.raises(SystemExit) as exc:
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert exc.value.code == 1
        assert "ws bad" in capsys.readouterr().err

    def test_agent_json_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            check_agent_json_profiles=lambda cfg: (False, "aj bad"),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "aj bad" in capsys.readouterr().err

    def test_enabled_agents_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            check_enabled_agents_load_agent_config=lambda cfg: (
                False,
                "acl bad",
            ),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "acl bad" in capsys.readouterr().err

    def test_cron_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            check_cron_jobs_files=lambda cfg: (False, "cron bad"),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "cron bad" in capsys.readouterr().err

    def test_active_llm_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            _check_active_llm=_async(lambda t, d: (False, "llm bad", [])),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "llm bad" in capsys.readouterr().err

    def test_model_connections_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            check_enabled_agents_model_connections=_async(
                lambda cfg, timeout, deep: (
                    False,
                    ["agent-a: FAIL — down"],
                    ["note"],
                ),
            ),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        combined = capsys.readouterr()
        assert "some enabled agents unreachable" in combined.err

    def test_model_connections_ok_lines_styled(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            check_enabled_agents_model_connections=_async(
                lambda cfg, timeout, deep: (
                    True,
                    ["agent-a: OK — up", "agent-b: FAIL — down\nextra"],
                    [],
                ),
            ),
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "all enabled agents reachable" in capsys.readouterr().out

    def test_health_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            _check_api_health=lambda base, t: (False, None),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)

    def test_version_not_reachable_exits(self, monkeypatch, capsys):
        calls = {"n": 0}

        def http_get(url, **kw):
            calls["n"] += 1
            raise httpx.ConnectError("version down")

        with _OkPatch(monkeypatch, _http_get=http_get):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "version not reachable" in capsys.readouterr().err

    def test_version_non_200_exits(self, monkeypatch, capsys):
        with _OkPatch(monkeypatch, _http_get=lambda u, **kw: _Resp(500)):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "version HTTP 500" in capsys.readouterr().err

    def test_version_mismatch_notes(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            _http_get=lambda u, **kw: _Resp(
                200,
                json_body={"version": "0.0.1"},
                headers={"content-type": "application/json"},
            ),
            __version__="9.9.9",
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "different installs or upgrade" in capsys.readouterr().out

    def test_console_root_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            _classify_console_root_response=lambda resp: (
                False,
                "console broken",
            ),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "console broken" in capsys.readouterr().err

    def test_console_get_raises_exits(self, monkeypatch, capsys):
        state = {"health_called": False}

        def health(base, t):
            state["health_called"] = True
            return True, _Resp(200)

        def http_get(url, **kw):
            if url.endswith("/api/version"):
                return _Resp(200, json_body={"version": "9.9.9"})
            raise httpx.ConnectError("root down")

        with _OkPatch(
            monkeypatch,
            _check_api_health=health,
            _http_get=http_get,
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "could not GET /" in capsys.readouterr().err

    def test_deep_runs_connectivity_section(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            collect_deep_channel_connectivity_notes=lambda cfg, t: [
                "telegram unreachable",
            ],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=True)
        out = capsys.readouterr().out
        assert "Channels (connectivity, --deep)" in out
        assert "telegram unreachable" in out

    def test_deep_no_connectivity_issues(self, monkeypatch, capsys):
        with _OkPatch(monkeypatch):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=True)
        assert "no connectivity warnings" in capsys.readouterr().out

    def test_unknown_config_keys_note(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            load_raw_config_dict=lambda: {"legacy_key": 1},
            scan_unknown_config_keys=lambda raw: ["legacy_key"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        out = capsys.readouterr().out
        assert "unknown keys" in out
        assert "legacy_key" in out

    def test_extension_contributions_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            run_extension_contributions=lambda ctx: [
                ("ext1", ["note a", "note b"]),
            ],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        out = capsys.readouterr().out
        assert "[ext1]" in out
        assert "note a" in out

    def test_legacy_workspace_note(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            legacy_single_agent_workspace_note=lambda cfg: "legacy note",
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        out = capsys.readouterr().out
        assert "Multi-agent / workspace" in out
        assert "legacy note" in out

    def test_channel_notes_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            enabled_channel_notes=lambda cfg: ["chan warn"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "chan warn" in capsys.readouterr().out

    def test_api_target_mismatch_note(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            api_target_mismatch_note=lambda cfg, base: "target differs",
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        out = capsys.readouterr().out
        assert "API target" in out
        assert "target differs" in out

    # ── remaining branch coverage: notes sections & FAIL variants ────

    def test_python_mismatch_note_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            _doctor_server_python_mismatch_note=lambda *a, **kw: (
                "venv mismatch detected"
            ),
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "venv mismatch detected" in capsys.readouterr().out

    def test_windows_environment_lines_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            windows_environment_lines=lambda: ["WIN line 1"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        out = capsys.readouterr().out
        assert "=== Windows environment ===" in out
        assert "WIN line 1" in out

    def test_mcp_notes_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            mcp_client_notes=lambda cfg: ["mcp warn"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "mcp warn" in capsys.readouterr().out

    def test_skill_notes_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            skill_layout_notes=lambda cfg: ["skill warn"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "skill warn" in capsys.readouterr().out

    def test_security_notes_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            security_baseline_notes=lambda cfg: ["sec warn"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        out = capsys.readouterr().out
        assert "review security posture" in out
        assert "sec warn" in out

    def test_memory_notes_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            memory_embedding_notes=lambda cfg: ["mem warn"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "mem warn" in capsys.readouterr().out

    def test_hygiene_notes_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            workspace_hygiene_notes=lambda cfg: ["hygiene warn"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "hygiene warn" in capsys.readouterr().out

    def test_config_invalid_deep_lists_connectivity_in_skip(
        self,
        monkeypatch,
        capsys,
    ):
        with _OkPatch(
            monkeypatch,
            strict_validate_config_file=lambda: (False, "broken"),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=True)
        assert "--deep connectivity" in capsys.readouterr().out

    def test_working_dir_fail_exits_and_skips_startup_paths(
        self,
        monkeypatch,
        capsys,
    ):
        with _OkPatch(
            monkeypatch,
            _check_working_dir=lambda: (False, "missing: /wd"),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        combined = capsys.readouterr()
        assert "missing: /wd" in combined.err
        assert "=== Startup paths ===" in combined.out
        assert "working directory not OK" in combined.out

    def test_app_log_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            check_app_log_writable=lambda: (False, "log locked"),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "log locked" in capsys.readouterr().err

    def test_workspace_writable_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            check_agent_workspace_writable=lambda cfg: (False, "ws locked"),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "ws locked" in capsys.readouterr().err

    def test_volume_disk_notes_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            startup_extra_volume_disk_notes=lambda cfg: ["disk note"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "disk note" in capsys.readouterr().out

    def test_console_static_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            _check_console_static_files=lambda: (False, "no bundle"),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "no bundle" in capsys.readouterr().err

    def test_console_static_notes_negative_styled_as_note(
        self,
        monkeypatch,
        capsys,
    ):
        with _OkPatch(
            monkeypatch,
            console_static_diagnostic_notes=lambda: [
                "npm on PATH: not found",
            ],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "npm on PATH: not found" in capsys.readouterr().out

    def test_web_auth_fail_exits(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            _check_web_auth=lambda base: (False, "no account"),
        ):
            with pytest.raises(SystemExit):
                dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "no account" in capsys.readouterr().err

    def test_provider_overview_exception_handled(self, monkeypatch, capsys):
        def boom():
            raise RuntimeError("registry down")

        with _OkPatch(monkeypatch, provider_overview_notes=boom):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "could not list providers" in capsys.readouterr().out

    def test_provider_overview_notes_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            provider_overview_notes=lambda: ["custom provider warn"],
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "custom provider warn" in capsys.readouterr().out

    def test_llm_notes_printed(self, monkeypatch, capsys):
        with _OkPatch(
            monkeypatch,
            _check_active_llm=_async(
                lambda t, d: (True, "llm ok", ["llm deep note"]),
            ),
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "llm deep note" in capsys.readouterr().out

    def test_version_json_unparseable_no_server_version(
        self,
        monkeypatch,
        capsys,
    ):
        with _OkPatch(
            monkeypatch,
            _http_get=lambda u, **kw: _Resp(
                200,
                raise_json=True,
                text="{",
                headers={"content-type": "application/json"},
            ),
        ):
            dc.run_doctor_checks(_ctx(), 1.0, 1.0, deep=False)
        assert "version (" in capsys.readouterr().out


class TestSamePythonExecutableResolveFallback:
    def test_resolve_oserror_falls_back_to_string_compare(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            dc.os.path,
            "samefile",
            lambda a, b: (_ for _ in ()).throw(OSError("no stat")),
        )

        real_resolve = dc.Path.resolve

        def boom_resolve(self, *a, **kw):
            raise OSError("cannot resolve")

        monkeypatch.setattr(dc.Path, "resolve", boom_resolve)
        try:
            assert dc._same_python_executable("/a", "/a") is True
            assert dc._same_python_executable("/a", "/b") is False
        finally:
            monkeypatch.setattr(dc.Path, "resolve", real_resolve)


# ---------------------------------------------------------------------------
# Click command wiring (doctor group / fix subcommand)
# ---------------------------------------------------------------------------


class TestDoctorCommandWiring:
    def test_no_subcommand_runs_checks(self, monkeypatch):
        called = {}

        def fake_checks(ctx, timeout, llm_timeout, deep):
            called["hit"] = (timeout, llm_timeout, deep)

        monkeypatch.setattr(dc, "run_doctor_checks", fake_checks)
        res = CliRunner().invoke(
            dc.doctor_cmd,
            ["--timeout", "2.5", "--llm-timeout", "3.5", "--deep"],
        )
        assert res.exit_code == 0
        assert called["hit"] == (2.5, 3.5, True)

    def test_fix_subcommand_delegates(self, monkeypatch):
        captured = {}

        def fake_fix(ctx, **kw):
            captured.update(kw)

        monkeypatch.setattr(dc, "_run_doctor_fix_cli", fake_fix)
        res = CliRunner().invoke(
            dc.doctor_cmd,
            ["fix", "--dry-run", "--yes", "--only", "a,b", "--no-backup"],
        )
        assert res.exit_code == 0
        assert captured["dry_run"] is True
        assert captured["yes"] is True
        assert captured["only"] == "a,b"
        assert captured["no_backup"] is True

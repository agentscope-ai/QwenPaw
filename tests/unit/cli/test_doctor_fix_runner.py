# -*- coding: utf-8 -*-
"""Unit tests for cli/doctor_fix_runner.py.

Covers path-allowlist helpers, cron normalization, backup/meta plumbing,
fix planning (``_plan_fixes``) and the full ``run_doctor_fix`` pipeline.
All filesystem mutations happen inside ``tmp_path``; module-level
collaborators (config loading, validation, repo-root detection, npm) are
monkeypatched on the runner module itself.
"""
# pylint: disable=protected-access,redefined-outer-name,superfluous-parens,unnecessary-lambda,unused-argument,unused-variable,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import json
from pathlib import Path

import pytest

import qwenpaw.cli.doctor_fix_runner as dfr


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wd(tmp_path):
    d = tmp_path / "wd"
    d.mkdir()
    return d


@pytest.fixture()
def no_config(monkeypatch):
    """No config.json anywhere -> strict_validate ok, load_config defaults."""
    monkeypatch.setattr(
        dfr,
        "strict_validate_config_file",
        lambda: (True, "(no file)"),
    )


@pytest.fixture()
def no_repo_root(monkeypatch):
    monkeypatch.setattr(
        dfr,
        "find_qwenpaw_source_repo_root",
        lambda: None,
    )


def _echo_factory():
    lines = []
    err_lines = []
    return lines, err_lines, lines.append, err_lines.append


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


class TestPathHelpers:
    def test_utc_session_id_shape(self):
        sid = dfr._utc_session_id()
        # "<UTC timestamp>Z-<8 hex>"
        ts, _, hex_part = sid.partition("-")
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(hex_part) == 8
        int(hex_part, 16)  # valid hex

    def test_workspace_under_working_dir(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        assert dfr.workspace_under_working_dir(wd / "ws", wd) is True
        assert dfr.workspace_under_working_dir(tmp_path / "elsewhere", wd) is (
            False
        )

    def test_path_allowed_for_write(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        assert dfr.path_allowed_for_write(wd / "a" / "b.json", wd) is True
        assert dfr.path_allowed_for_write(tmp_path / "out.json", wd) is False

    def test_relative_under_wd(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        assert dfr._relative_under_wd(wd / "x.json", wd) == Path("x.json")


class TestNormalizeCronFields:
    def test_no_jobs_key(self):
        assert dfr._normalize_cron_fields_in_jobs_dict({}) is False

    def test_jobs_not_list(self):
        assert dfr._normalize_cron_fields_in_jobs_dict({"jobs": "x"}) is False

    def test_non_dict_jobs_and_non_dict_schedules_skipped(self):
        data = {
            "jobs": [
                "not-a-dict",
                {"id": "j0", "schedule": "nope"},
                {"id": "j1", "schedule": {"cron": 42}},
            ],
        }
        assert dfr._normalize_cron_fields_in_jobs_dict(data) is False

    def test_numeric_dow_converted(self):
        data = {
            "jobs": [
                {
                    "id": "j1",
                    "schedule": {"cron": "0 9 * * 1", "timezone": "UTC"},
                },
            ],
        }
        assert dfr._normalize_cron_fields_in_jobs_dict(data) is True
        assert data["jobs"][0]["schedule"]["cron"] == "0 9 * * mon"

    def test_non_string_timezone_normalized_as_utc(self):
        # non-string timezone is treated as UTC for validation; the
        # stored value is left untouched, only cron gets rewritten
        data = {
            "jobs": [
                {
                    "id": "j1",
                    "schedule": {"cron": "0 9 * * 1", "timezone": 123},
                },
            ],
        }
        assert dfr._normalize_cron_fields_in_jobs_dict(data) is True
        sch = data["jobs"][0]["schedule"]
        assert sch["cron"] == "0 9 * * mon"
        assert sch["timezone"] == 123

    def test_already_normalized_no_change(self):
        data = {
            "jobs": [
                {
                    "id": "j1",
                    "schedule": {"cron": "0 9 * * mon", "timezone": "UTC"},
                },
            ],
        }
        assert dfr._normalize_cron_fields_in_jobs_dict(data) is False

    def test_invalid_cron_raises(self):
        # two-field cron cannot be normalized -> ScheduleSpec raises
        data = {"jobs": [{"id": "j1", "schedule": {"cron": "0 9"}}]}
        with pytest.raises(ValueError, match="invalid cron"):
            dfr._normalize_cron_fields_in_jobs_dict(data)


class TestWorkspaceAgentJsonValid:
    def test_missing_file(self, tmp_path):
        assert dfr._workspace_agent_json_valid(tmp_path / "a.json") is False

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text("{bad")
        assert dfr._workspace_agent_json_valid(p) is False

    def test_non_dict_root(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text("[1, 2]")
        assert dfr._workspace_agent_json_valid(p) is False

    def test_schema_invalid(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text(json.dumps({"id": 123, "bogus_field": True}))
        assert dfr._workspace_agent_json_valid(p) is False

    def test_normalize_paths_exception_is_swallowed(
        self,
        tmp_path,
        monkeypatch,
    ):
        p = tmp_path / "a.json"
        p.write_text(
            json.dumps(
                {
                    "id": "ag1",
                    "name": "Ag1",
                    "workspace_dir": str(tmp_path),
                },
            ),
        )

        def boom(data):
            raise RuntimeError("weird structure")

        monkeypatch.setattr(
            dfr,
            "_normalize_working_dir_bound_paths",
            boom,
        )
        # normalization failure must not reject the profile
        assert dfr._workspace_agent_json_valid(p) is True

    def test_valid_profile(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text(
            json.dumps(
                {
                    "id": "ag1",
                    "name": "Ag1",
                    "workspace_dir": str(tmp_path),
                },
            ),
        )
        assert dfr._workspace_agent_json_valid(p) is True


class TestAtomicWriteText:
    def test_writes_content_and_no_leftover_tmp(self, tmp_path):
        p = tmp_path / "deep" / "a.json"
        dfr._atomic_write_text(p, '{"x": 1}')
        assert p.read_text() == '{"x": 1}'
        leftovers = [x for x in p.parent.iterdir() if x.name != "a.json"]
        assert leftovers == []

    def test_chmod_failure_is_swallowed(self, tmp_path, monkeypatch):
        p = tmp_path / "a.json"
        monkeypatch.setattr(
            dfr.os,
            "chmod",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("no chmod")),
        )
        dfr._atomic_write_text(p, "x")
        assert p.read_text() == "x"

    def test_replace_failure_cleans_up_tmp(self, tmp_path, monkeypatch):
        p = tmp_path / "a.json"

        def boom_replace(self, target):
            raise OSError("cannot replace")

        monkeypatch.setattr(dfr.Path, "replace", boom_replace)
        with pytest.raises(OSError, match="cannot replace"):
            dfr._atomic_write_text(p, "x")
        leftovers = [x for x in tmp_path.iterdir() if x.name != "a.json"]
        assert leftovers == []

    def test_unlink_failure_in_cleanup_is_swallowed(
        self,
        tmp_path,
        monkeypatch,
    ):
        p = tmp_path / "a.json"

        def boom_replace(self, target):
            raise OSError("cannot replace")

        def boom_unlink(self, *a, **kw):
            raise OSError("locked")

        monkeypatch.setattr(dfr.Path, "replace", boom_replace)
        monkeypatch.setattr(dfr.Path, "unlink", boom_unlink)
        # original replace error propagates; unlink OSError is swallowed
        with pytest.raises(OSError, match="cannot replace"):
            dfr._atomic_write_text(p, "x")


class TestBackupOneFile:
    def test_existing_file_copied(self, tmp_path):
        wd = tmp_path / "wd"
        ws = wd / "ws"
        ws.mkdir(parents=True)
        src = ws / "jobs.json"
        src.write_text("payload")
        session = tmp_path / "session" / "files"
        session.mkdir(parents=True)
        dfr._backup_one_file(session, src, wd)
        assert (session / "ws" / "jobs.json").read_text() == "payload"

    def test_missing_file_writes_marker(self, tmp_path):
        wd = tmp_path / "wd"
        (wd / "ws").mkdir(parents=True)
        session = tmp_path / "session" / "files"
        session.mkdir(parents=True)
        missing = wd / "ws" / "gone.json"
        dfr._backup_one_file(session, missing, wd)
        assert (session / "ws" / "gone.json.MISSING").exists()


class TestEffectiveCliApiHostPort:
    def test_both_overrides_win(self, monkeypatch):
        monkeypatch.setattr(dfr, "read_last_api", lambda: ("h", 1))
        assert dfr._effective_cli_api_host_port("x", 2) == ("x", 2)

    def test_missing_filled_from_last_api(self, monkeypatch):
        monkeypatch.setattr(dfr, "read_last_api", lambda: ("h9", 9999))
        assert dfr._effective_cli_api_host_port(None, None) == (
            "h9",
            9999,
        )

    def test_defaults_when_no_last_api(self, monkeypatch):
        monkeypatch.setattr(dfr, "read_last_api", lambda: None)
        assert dfr._effective_cli_api_host_port(None, None) == (
            "127.0.0.1",
            8088,
        )


class TestWriteMeta:
    def test_meta_json_written(self, tmp_path, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "load_config",
            lambda: _CfgWithLastApi("10.0.0.1", 7777),
        )
        monkeypatch.setattr(
            dfr,
            "read_last_api",
            lambda: ("10.0.0.1", 7777),
        )
        session = wd / "sess"
        session.mkdir()
        dfr._write_meta(
            session,
            ["doctor", "fix"],
            ["ensure-working-dir"],
            ["ws/jobs.json"],
            working_dir=str(wd),
            dry_run=False,
            yes=True,
            no_backup=False,
            non_interactive=False,
            cli_api_host=None,
            cli_api_port=None,
        )
        meta = json.loads((session / "meta.json").read_text())
        assert meta["fix_ids"] == ["ensure-working-dir"]
        assert meta["working_dir"] == str(wd)
        assert meta["cli_resolved_api"]["host"] == "10.0.0.1"
        assert meta["cli_resolved_api"]["port"] == 7777
        assert meta["cli_resolved_api"]["base_url"] == "http://10.0.0.1:7777"
        assert meta["config_last_api"]["host"] == "10.0.0.1"


class _CfgWithLastApi:
    def __init__(self, host, port):
        self.last_api = _LastApi(host, port)


class _LastApi:
    def __init__(self, host, port):
        self.host = host
        self.port = port


# ---------------------------------------------------------------------------
# _parse_only
# ---------------------------------------------------------------------------


class TestParseOnly:
    def test_empty_defaults_to_safe_sorted(self):
        assert dfr._parse_only(None) == sorted(dfr.SAFE_FIX_IDS)
        assert dfr._parse_only("  ") == sorted(dfr.SAFE_FIX_IDS)

    def test_explicit_ids_split(self):
        got = dfr._parse_only("ensure-working-dir, seed-missing-agent-json")
        assert got == ["ensure-working-dir", "seed-missing-agent-json"]

    def test_unknown_id_raises(self):
        with pytest.raises(ValueError, match="unknown fix id"):
            dfr._parse_only("no-such-id")


class TestFixIdSets:
    def test_all_is_union(self):
        assert dfr.ALL_FIX_IDS == (
            dfr.SAFE_FIX_IDS
            | dfr.READONLY_FIX_IDS
            | dfr.SYNC_FIX_IDS
            | dfr.RISKY_FIX_IDS
        )

    def test_noninteractive_excludes_risky(self):
        assert dfr.NONINTERACTIVE_FIX_IDS == (
            dfr.SAFE_FIX_IDS | dfr.READONLY_FIX_IDS | dfr.SYNC_FIX_IDS
        )
        assert not (dfr.NONINTERACTIVE_FIX_IDS & dfr.RISKY_FIX_IDS)


# ---------------------------------------------------------------------------
# _plan_fixes
# ---------------------------------------------------------------------------


class TestPlanFixes:
    def test_risky_requires_yes(self, wd, monkeypatch):
        with pytest.raises(ValueError, match="requires --yes"):
            dfr._plan_fixes(["seed-missing-agent-json"], wd, yes=False)

    def test_risky_allowed_with_dry_run(self, wd, monkeypatch, no_config):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        msgs, planned = dfr._plan_fixes(
            ["seed-missing-agent-json"],
            wd,
            yes=False,
            dry_run=True,
        )
        assert planned == []

    def test_missing_wd_requires_ensure_working_dir(
        self,
        tmp_path,
        monkeypatch,
    ):
        gone = tmp_path / "nowhere"
        with pytest.raises(ValueError, match="does not exist"):
            dfr._plan_fixes(["ensure-workspace-dirs"], gone, yes=True)

    def test_ensure_working_dir_planned_when_missing(
        self,
        tmp_path,
        monkeypatch,
        no_config,
    ):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        target = tmp_path / "wd_new"
        msgs, planned = dfr._plan_fixes(
            ["ensure-working-dir"],
            target,
            yes=True,
        )
        assert [p.fix_id for p in planned] == ["ensure-working-dir"]
        planned[0].apply_fn()
        assert target.is_dir()

    def test_ensure_working_dir_parent_missing(self, tmp_path):
        target = tmp_path / "no_parent" / "wd"
        with pytest.raises(ValueError, match="parent directory"):
            dfr._plan_fixes(["ensure-working-dir"], target, yes=True)

    def test_ensure_working_dir_parent_not_writable(
        self,
        tmp_path,
        monkeypatch,
    ):
        target = tmp_path / "ro" / "wd"
        (tmp_path / "ro").mkdir()
        monkeypatch.setattr(dfr.os, "access", lambda p, m: False)
        with pytest.raises(ValueError, match="not writable"):
            dfr._plan_fixes(["ensure-working-dir"], target, yes=True)

    def test_ensure_working_dir_noop_when_exists(
        self,
        wd,
        monkeypatch,
        no_config,
    ):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        msgs, planned = dfr._plan_fixes(["ensure-working-dir"], wd, yes=True)
        assert planned == []

    def test_load_config_failure_records_skip(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )

        def boom():
            raise RuntimeError("config exploded")

        monkeypatch.setattr(dfr, "load_config", boom)
        msgs, planned = dfr._plan_fixes(
            ["validate-all-jobs-json"],
            wd,
            yes=True,
        )
        assert any("load_config failed" in m for m in msgs)
        assert planned == []

    def test_validate_all_jobs_json_ok_and_fail(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        cfg = _EmptyCfg()
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        monkeypatch.setattr(
            dfr,
            "check_cron_jobs_files",
            lambda c: (True, "all good"),
        )
        msgs, _ = dfr._plan_fixes(["validate-all-jobs-json"], wd, yes=True)
        assert msgs == ["validate-all-jobs-json: OK — all good"]
        monkeypatch.setattr(
            dfr,
            "check_cron_jobs_files",
            lambda c: (False, "bad file"),
        )
        msgs, _ = dfr._plan_fixes(["validate-all-jobs-json"], wd, yes=True)
        assert msgs == ["validate-all-jobs-json: FAIL — bad file"]

    def test_validate_all_jobs_json_config_invalid(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (False, "broken"),
        )
        msgs, planned = dfr._plan_fixes(
            ["validate-all-jobs-json"],
            wd,
            yes=True,
        )
        assert any("skipped" in m for m in msgs)
        assert planned == []


class TestPlanSkipBranches:
    """Each fix-id loop skips agents outside wd / without dirs."""

    def _cfg_outside_and_missing(self, wd):
        return _Cfg(
            {
                "outside": _Ref(str(wd.parent / "elsewhere_ws")),
                "nodir": _Ref(str(wd / "ghost_ws")),
            },
        )

    def _patch(self, monkeypatch, cfg):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)

    def test_ensure_workspace_dirs_skips_existing(self, wd, monkeypatch):
        ws = wd / "ws_exists"
        ws.mkdir()
        cfg = _Cfg({"ok": _Ref(str(ws))})
        self._patch(monkeypatch, cfg)
        msgs, planned = dfr._plan_fixes(
            ["ensure-workspace-dirs"],
            wd,
            yes=True,
        )
        assert planned == []

    def test_seed_skips_outside_and_missing_ws(self, wd, monkeypatch):
        self._patch(monkeypatch, self._cfg_outside_and_missing(wd))
        msgs, planned = dfr._plan_fixes(
            ["seed-missing-agent-json"],
            wd,
            yes=True,
        )
        assert planned == []

    def test_reset_skips_outside_missing_and_valid(
        self,
        wd,
        monkeypatch,
    ):
        valid = wd / "ws_valid"
        valid.mkdir()
        (valid / "agent.json").write_text(
            json.dumps(
                {
                    "id": "ok",
                    "name": "Ok",
                    "workspace_dir": str(valid),
                },
            ),
        )
        nofile = wd / "ws_nofile"
        nofile.mkdir()
        cfg = _Cfg(
            {
                "outside": _Ref(str(wd.parent / "elsewhere_ws")),
                "nodir": _Ref(str(wd / "ghost_ws")),
                "ok": _Ref(str(valid)),
                "nofile": _Ref(str(nofile)),
            },
        )
        self._patch(monkeypatch, cfg)
        msgs, planned = dfr._plan_fixes(
            ["reset-invalid-agent-json"],
            wd,
            yes=True,
        )
        assert planned == []

    def test_write_empty_jobs_skips_outside_missing_and_existing(
        self,
        wd,
        monkeypatch,
    ):
        has = wd / "ws_has"
        has.mkdir()
        (has / "jobs.json").write_text('{"version": 2, "jobs": []}')
        cfg = _Cfg(
            {
                "outside": _Ref(str(wd.parent / "elsewhere_ws")),
                "nodir": _Ref(str(wd / "ghost_ws")),
                "has": _Ref(str(has)),
            },
        )
        self._patch(monkeypatch, cfg)
        msgs, planned = dfr._plan_fixes(
            ["write-empty-jobs-json"],
            wd,
            yes=True,
        )
        assert planned == []

    def test_reconcile_skips_outside_and_missing(self, wd, monkeypatch):
        self._patch(monkeypatch, self._cfg_outside_and_missing(wd))
        monkeypatch.setattr(
            dfr,
            "get_workspace_skill_manifest_path",
            lambda w: w / "skill.json",
        )
        msgs, planned = dfr._plan_fixes(
            ["reconcile-workspace-skills"],
            wd,
            yes=True,
        )
        assert planned == []

    def test_reconcile_without_existing_manifest_no_backup(
        self,
        wd,
        monkeypatch,
    ):
        ws = wd / "ws"
        ws.mkdir()
        cfg = _Cfg({"a": _Ref(str(ws))})
        self._patch(monkeypatch, cfg)
        monkeypatch.setattr(
            dfr,
            "get_workspace_skill_manifest_path",
            lambda w: w / "skill.json",
        )
        monkeypatch.setattr(
            dfr,
            "reconcile_workspace_manifest",
            lambda w: None,
        )
        msgs, planned = dfr._plan_fixes(
            ["reconcile-workspace-skills"],
            wd,
            yes=True,
        )
        assert planned[0].paths_to_backup == ()

    def test_normalize_skips_outside_missing_and_no_jobs(
        self,
        wd,
        monkeypatch,
    ):
        nojobs = wd / "ws_nojobs"
        nojobs.mkdir()  # no jobs.json inside
        cfg = _Cfg(
            {
                "outside": _Ref(str(wd.parent / "elsewhere_ws")),
                "nodir": _Ref(str(wd / "ghost_ws")),
                "nojobs": _Ref(str(nojobs)),
            },
        )
        self._patch(monkeypatch, cfg)
        msgs, planned = dfr._plan_fixes(
            ["normalize-jobs-cron"],
            wd,
            yes=True,
        )
        assert planned == []

    def test_normalize_already_normalized_no_change(
        self,
        wd,
        monkeypatch,
    ):
        ws = wd / "ws"
        ws.mkdir()
        (ws / "jobs.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "jobs": [_valid_job("j1", "0 9 * * mon")],
                },
            ),
        )
        cfg = _Cfg({"a": _Ref(str(ws))})
        self._patch(monkeypatch, cfg)
        msgs, planned = dfr._plan_fixes(
            ["normalize-jobs-cron"],
            wd,
            yes=True,
        )
        assert planned == []


class _EmptyCfg:
    class _A:
        profiles = {}

    agents = _A()
    last_api = _LastApi("127.0.0.1", 8088)


def _valid_job(job_id: str, cron: str) -> dict:
    """Minimal CronJobSpec payload that passes JobsFile validation."""
    return {
        "id": job_id,
        "name": job_id,
        "enabled": True,
        "schedule": {"type": "cron", "cron": cron, "timezone": "UTC"},
        "task_type": "text",
        "text": "hello",
        "dispatch": {
            "type": "channel",
            "channel": "test",
            "target": {"user_id": "u", "session_id": "s"},
            "mode": "final",
        },
    }


class _Ref:
    def __init__(self, ws):
        self.workspace_dir = ws


class _CfgProfiles:
    def __init__(self, profiles):
        self.profiles = profiles


class _Cfg:
    def __init__(self, profiles):
        self.agents = _CfgProfiles(profiles)
        self.last_api = _LastApi("127.0.0.1", 8088)


class TestPlanWorkspaceFixes:
    def test_ensure_workspace_dirs_creates_missing(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "workspaces" / "ag1"
        outside = wd.parent / "outside_ws"
        cfg = _Cfg(
            {"ag1": _Ref(str(ws)), "ag2": _Ref(str(outside))},
        )
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        msgs, planned = dfr._plan_fixes(
            ["ensure-workspace-dirs"],
            wd,
            yes=True,
        )
        assert [p.fix_id for p in planned] == ["ensure-workspace-dirs"]
        planned[0].apply_fn()
        assert ws.is_dir()

    def test_ensure_workspace_dirs_guard_rejects_outside_path(
        self,
        wd,
        monkeypatch,
    ):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws1"
        cfg = _Cfg({"ag1": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        _, planned = dfr._plan_fixes(["ensure-workspace-dirs"], wd, yes=True)
        op = planned[0]
        # simulate path no longer under wd at apply time
        monkeypatch.setattr(
            dfr,
            "path_allowed_for_write",
            lambda t, r: False,
        )
        with pytest.raises(RuntimeError, match="path not allowed"):
            op.apply_fn()

    def test_seed_missing_agent_json(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws1"
        ws.mkdir()
        with_agent = wd / "ws2"
        with_agent.mkdir()
        (with_agent / "agent.json").write_text("{}")
        no_ws = wd / "missing_ws"  # workspace dir missing -> skip
        cfg = _Cfg(
            {
                "ag1": _Ref(str(ws)),
                "ag2": _Ref(str(with_agent)),
                "ag3": _Ref(str(no_ws)),
            },
        )
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        msgs, planned = dfr._plan_fixes(
            ["seed-missing-agent-json"],
            wd,
            yes=True,
        )
        assert [p.fix_id for p in planned] == ["seed-missing-agent-json"]
        op = planned[0]
        assert op.paths_to_backup == (ws / "agent.json",)
        op.apply_fn()
        seeded = json.loads((ws / "agent.json").read_text())
        assert seeded["id"] == "ag1"
        # re-apply is a no-op when file exists now
        op.apply_fn()
        assert (ws / "agent.json").is_file()

    def test_seed_guard_rejects_outside_path(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws1"
        ws.mkdir()
        cfg = _Cfg({"ag1": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        _, planned = dfr._plan_fixes(
            ["seed-missing-agent-json"],
            wd,
            yes=True,
        )
        monkeypatch.setattr(
            dfr,
            "path_allowed_for_write",
            lambda t, r: False,
        )
        with pytest.raises(RuntimeError, match="path not allowed"):
            planned[0].apply_fn()

    def test_reset_invalid_agent_json(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws1"
        ws.mkdir()
        (ws / "agent.json").write_text("{invalid")
        good = wd / "ws2"
        good.mkdir()
        (good / "agent.json").write_text(
            json.dumps(
                {
                    "id": "ag2",
                    "name": "Ag2",
                    "workspace_dir": str(good),
                },
            ),
        )
        cfg = _Cfg({"ag1": _Ref(str(ws)), "ag2": _Ref(str(good))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        msgs, planned = dfr._plan_fixes(
            ["reset-invalid-agent-json"],
            wd,
            yes=True,
        )
        assert [p.fix_id for p in planned] == ["reset-invalid-agent-json"]
        planned[0].apply_fn()
        reset = json.loads((ws / "agent.json").read_text())
        assert reset["id"] == "ag1"

    def test_reset_guard_rejects_outside_path(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws1"
        ws.mkdir()
        (ws / "agent.json").write_text("{invalid")
        cfg = _Cfg({"ag1": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        _, planned = dfr._plan_fixes(
            ["reset-invalid-agent-json"],
            wd,
            yes=True,
        )
        monkeypatch.setattr(
            dfr,
            "path_allowed_for_write",
            lambda t, r: False,
        )
        with pytest.raises(RuntimeError, match="path not allowed"):
            planned[0].apply_fn()

    def test_write_empty_jobs_json(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws1"
        ws.mkdir()
        has_jobs = wd / "ws2"
        has_jobs.mkdir()
        (has_jobs / "jobs.json").write_text('{"version": 1, "jobs": []}')
        cfg = _Cfg({"ag1": _Ref(str(ws)), "ag2": _Ref(str(has_jobs))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        msgs, planned = dfr._plan_fixes(
            ["write-empty-jobs-json"],
            wd,
            yes=True,
        )
        assert [p.fix_id for p in planned] == ["write-empty-jobs-json"]
        op = planned[0]
        op.apply_fn()
        body = json.loads((ws / "jobs.json").read_text())
        assert body["version"] == 1
        assert body["jobs"] == []
        # idempotent no-op
        op.apply_fn()

    def test_write_empty_jobs_guard(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws1"
        ws.mkdir()
        cfg = _Cfg({"ag1": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        _, planned = dfr._plan_fixes(["write-empty-jobs-json"], wd, yes=True)
        monkeypatch.setattr(
            dfr,
            "path_allowed_for_write",
            lambda t, r: False,
        )
        with pytest.raises(RuntimeError, match="path not allowed"):
            planned[0].apply_fn()

    def test_reconcile_workspace_skills(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws1"
        ws.mkdir()
        manifest = ws / "skill.json"
        manifest.write_text("{}")
        cfg = _Cfg({"ag1": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        monkeypatch.setattr(
            dfr,
            "get_workspace_skill_manifest_path",
            lambda w: w / "skill.json",
        )
        calls = []
        monkeypatch.setattr(
            dfr,
            "reconcile_workspace_manifest",
            lambda w: calls.append(w),
        )
        msgs, planned = dfr._plan_fixes(
            ["reconcile-workspace-skills"],
            wd,
            yes=True,
        )
        assert [p.fix_id for p in planned] == ["reconcile-workspace-skills"]
        op = planned[0]
        assert op.paths_to_backup == (manifest,)
        op.apply_fn()
        assert calls == [ws]

    def test_reconcile_guard(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws1"
        ws.mkdir()
        cfg = _Cfg({"ag1": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        monkeypatch.setattr(
            dfr,
            "get_workspace_skill_manifest_path",
            lambda w: w / "skill.json",
        )
        _, planned = dfr._plan_fixes(
            ["reconcile-workspace-skills"],
            wd,
            yes=True,
        )
        # guard fires inside apply_fn when the workspace is no longer
        # under the working directory at apply time
        monkeypatch.setattr(
            dfr,
            "workspace_under_working_dir",
            lambda w, r: False,
        )
        with pytest.raises(RuntimeError, match="path not allowed"):
            planned[0].apply_fn()

    def test_normalize_jobs_cron_variants(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws_ok = wd / "ws_ok"
        ws_ok.mkdir()
        (ws_ok / "jobs.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "jobs": [_valid_job("j1", "0 9 * * 1")],
                },
            ),
        )
        ws_broken = wd / "ws_broken"
        ws_broken.mkdir()
        (ws_broken / "jobs.json").write_text("{broken")
        ws_nonobj = wd / "ws_nonobj"
        ws_nonobj.mkdir()
        (ws_nonobj / "jobs.json").write_text("[1]")
        ws_badcron = wd / "ws_badcron"
        ws_badcron.mkdir()
        (ws_badcron / "jobs.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "jobs": [{"id": "j2", "schedule": {"cron": "0 9"}}],
                },
            ),
        )
        ws_invalid = wd / "ws_invalid"
        ws_invalid.mkdir()
        # cron normalizes fine, but the resulting file still fails
        # JobsFile validation (bad dispatch shape)
        bad_job = _valid_job("j3", "0 9 * * 1")
        del bad_job["dispatch"]
        (ws_invalid / "jobs.json").write_text(
            json.dumps({"version": 2, "jobs": [bad_job]}),
        )
        ws_no_jobs = wd / "ws_no_jobs"
        ws_no_jobs.mkdir()
        cfg = _Cfg(
            {
                "ok": _Ref(str(ws_ok)),
                "broken": _Ref(str(ws_broken)),
                "nonobj": _Ref(str(ws_nonobj)),
                "badcron": _Ref(str(ws_badcron)),
                "invalid": _Ref(str(ws_invalid)),
                "nojobs": _Ref(str(ws_no_jobs)),
            },
        )
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        msgs, planned = dfr._plan_fixes(["normalize-jobs-cron"], wd, yes=True)
        assert [p.fix_id for p in planned] == ["normalize-jobs-cron"]
        joined = "\n".join(msgs)
        assert "broken" in joined
        assert "root must be a JSON object" in joined
        assert "invalid cron" in joined
        assert "invalid after cron normalize" in joined
        planned[0].apply_fn()
        body = json.loads((ws_ok / "jobs.json").read_text())
        assert body["jobs"][0]["schedule"]["cron"] == "0 9 * * mon"

    def test_normalize_jobs_cron_guard(self, wd, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws"
        ws.mkdir()
        (ws / "jobs.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "jobs": [_valid_job("j1", "0 9 * * 1")],
                },
            ),
        )
        cfg = _Cfg({"a": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        _, planned = dfr._plan_fixes(["normalize-jobs-cron"], wd, yes=True)
        monkeypatch.setattr(
            dfr,
            "path_allowed_for_write",
            lambda t, r: False,
        )
        with pytest.raises(RuntimeError, match="path not allowed"):
            planned[0].apply_fn()


class TestPlanRebuildConsole:
    def test_not_in_source_checkout(self, wd, monkeypatch, no_repo_root):
        msgs, planned = dfr._plan_fixes(["rebuild-console-npm"], wd, yes=True)
        assert any("source checkout" in m for m in msgs)
        assert planned == []

    def test_npm_missing(self, wd, monkeypatch, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        monkeypatch.setattr(
            dfr,
            "find_qwenpaw_source_repo_root",
            lambda: repo,
        )
        monkeypatch.setattr(dfr.shutil, "which", lambda n: None)
        msgs, planned = dfr._plan_fixes(["rebuild-console-npm"], wd, yes=True)
        assert any("npm not found" in m for m in msgs)
        assert planned == []

    def test_rebuild_planned_and_applies(self, wd, monkeypatch, tmp_path):
        repo = tmp_path / "repo"
        console = repo / "console"
        console.mkdir(parents=True)
        (console / "package.json").write_text("{}")
        (console / "package-lock.json").write_text("{}")
        dist = console / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>")
        target = repo / "src" / "qwenpaw" / "console"
        target.mkdir(parents=True)
        (target / "old.js").write_text("old")
        monkeypatch.setattr(
            dfr,
            "find_qwenpaw_source_repo_root",
            lambda: repo,
        )
        monkeypatch.setattr(dfr.shutil, "which", lambda n: "/usr/bin/npm")
        ran = []
        monkeypatch.setattr(
            dfr.subprocess,
            "run",
            lambda cmd, **kw: ran.append(cmd),
        )
        msgs, planned = dfr._plan_fixes(["rebuild-console-npm"], wd, yes=True)
        assert [p.fix_id for p in planned] == ["rebuild-console-npm"]
        planned[0].apply_fn()
        assert [c[:2] for c in ran] == [["npm", "ci"], ["npm", "run"]]
        # previous bundle backed up, then replaced by dist
        assert (target / "index.html").is_file()
        assert not (target / "old.js").exists()
        bkp_root = repo / ".qwenpaw-doctor-fix-backups"
        sessions = list(bkp_root.iterdir())
        assert len(sessions) == 1
        assert (sessions[0] / "meta.json").is_file()
        prev = sessions[0] / "previous-console-bundle"
        assert (prev / "old.js").is_file()

    def test_rebuild_no_backup_skips_prev_backup(
        self,
        wd,
        monkeypatch,
        tmp_path,
    ):
        repo = tmp_path / "repo"
        console = repo / "console"
        console.mkdir(parents=True)
        (console / "package-lock.json").write_text("{}")
        dist = console / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>")
        monkeypatch.setattr(
            dfr,
            "find_qwenpaw_source_repo_root",
            lambda: repo,
        )
        monkeypatch.setattr(dfr.shutil, "which", lambda n: "/usr/bin/npm")
        monkeypatch.setattr(
            dfr.subprocess,
            "run",
            lambda cmd, **kw: None,
        )
        msgs, planned = dfr._plan_fixes(
            ["rebuild-console-npm"],
            wd,
            yes=True,
            no_backup=True,
        )
        planned[0].apply_fn()
        assert not (repo / ".qwenpaw-doctor-fix-backups").exists()

    def test_rebuild_prev_bundle_slot_replaced(
        self,
        wd,
        monkeypatch,
        tmp_path,
    ):
        """Pre-existing previous-console-bundle dir is removed first."""
        repo = tmp_path / "repo"
        console = repo / "console"
        console.mkdir(parents=True)
        (console / "package-lock.json").write_text("{}")
        dist = console / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>")
        target = repo / "src" / "qwenpaw" / "console"
        target.mkdir(parents=True)
        (target / "cur.js").write_text("cur")
        monkeypatch.setattr(
            dfr,
            "find_qwenpaw_source_repo_root",
            lambda: repo,
        )
        monkeypatch.setattr(dfr.shutil, "which", lambda n: "/usr/bin/npm")
        monkeypatch.setattr(
            dfr.subprocess,
            "run",
            lambda cmd, **kw: None,
        )
        _, planned = dfr._plan_fixes(["rebuild-console-npm"], wd, yes=True)
        op = planned[0]
        # simulate a same-second second run: session dir & prev already there
        monkeypatch.setattr(dfr, "_utc_session_id", lambda: "FIXEDSID")
        prev = (
            repo
            / ".qwenpaw-doctor-fix-backups"
            / "FIXEDSID"
            / "previous-console-bundle"
        )
        prev.mkdir(parents=True)
        (prev / "stale.js").write_text("stale")
        op.apply_fn()
        assert not (prev / "stale.js").exists()
        assert (prev / "cur.js").is_file()

    def test_rebuild_missing_console_dir(self, wd, monkeypatch, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        monkeypatch.setattr(
            dfr,
            "find_qwenpaw_source_repo_root",
            lambda: repo,
        )
        monkeypatch.setattr(dfr.shutil, "which", lambda n: "/usr/bin/npm")
        _, planned = dfr._plan_fixes(["rebuild-console-npm"], wd, yes=True)
        with pytest.raises(RuntimeError, match="missing console directory"):
            planned[0].apply_fn()

    def test_rebuild_missing_lockfile(self, wd, monkeypatch, tmp_path):
        repo = tmp_path / "repo"
        console = repo / "console"
        console.mkdir(parents=True)
        monkeypatch.setattr(
            dfr,
            "find_qwenpaw_source_repo_root",
            lambda: repo,
        )
        monkeypatch.setattr(dfr.shutil, "which", lambda n: "/usr/bin/npm")
        _, planned = dfr._plan_fixes(["rebuild-console-npm"], wd, yes=True)
        with pytest.raises(RuntimeError, match="package-lock.json"):
            planned[0].apply_fn()

    def test_rebuild_missing_dist_after_build(
        self,
        wd,
        monkeypatch,
        tmp_path,
    ):
        repo = tmp_path / "repo"
        console = repo / "console"
        console.mkdir(parents=True)
        (console / "package-lock.json").write_text("{}")
        monkeypatch.setattr(
            dfr,
            "find_qwenpaw_source_repo_root",
            lambda: repo,
        )
        monkeypatch.setattr(dfr.shutil, "which", lambda n: "/usr/bin/npm")
        monkeypatch.setattr(
            dfr.subprocess,
            "run",
            lambda cmd, **kw: None,
        )
        _, planned = dfr._plan_fixes(["rebuild-console-npm"], wd, yes=True)
        with pytest.raises(RuntimeError, match="index.html"):
            planned[0].apply_fn()


# ---------------------------------------------------------------------------
# run_doctor_fix (full pipeline)
# ---------------------------------------------------------------------------


class TestRunDoctorFix:
    def _run(self, **kw):
        lines, err, echo, echo_err = _echo_factory()
        code = dfr.run_doctor_fix(
            echo=echo,
            echo_err=echo_err,
            confirm_fn=kw.pop("confirm_fn", None),
            **kw,
        )
        return code, lines, err

    def test_unknown_only_returns_1(self, wd):
        code, lines, err = self._run(
            dry_run=False,
            yes=False,
            only="bogus",
            no_backup=False,
            backup_dir=None,
            working_dir=wd,
        )
        assert code == 1
        assert any("unknown fix id" in e for e in err)

    def test_non_interactive_rejects_risky(self, wd):
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only="rebuild-console-npm",
            no_backup=False,
            backup_dir=None,
            working_dir=wd,
            non_interactive=True,
        )
        assert code == 1
        assert any("--non-interactive" in e for e in err)

    def test_plan_error_returns_1(self, wd):
        code, lines, err = self._run(
            dry_run=False,
            yes=False,
            only="seed-missing-agent-json",
            no_backup=False,
            backup_dir=None,
            working_dir=wd,
        )
        assert code == 1
        assert any("requires --yes" in e for e in err)

    def test_nothing_to_do(self, wd, monkeypatch, no_config, no_repo_root):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only=None,
            no_backup=False,
            backup_dir=None,
            working_dir=wd,
        )
        assert code == 0
        assert any("Nothing to do" in line for line in lines)

    def test_readonly_validation_only_ok_and_fail(
        self,
        wd,
        monkeypatch,
        no_repo_root,
    ):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        monkeypatch.setattr(
            dfr,
            "check_cron_jobs_files",
            lambda c: (True, "fine"),
        )
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only="validate-all-jobs-json",
            no_backup=False,
            backup_dir=None,
            working_dir=wd,
        )
        assert code == 0
        assert any("read-only jobs.json validation" in line for line in lines)
        monkeypatch.setattr(
            dfr,
            "check_cron_jobs_files",
            lambda c: (False, "broken"),
        )
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only="validate-all-jobs-json",
            no_backup=False,
            backup_dir=None,
            working_dir=wd,
        )
        assert code == 1

    def test_dry_run_lists_plan_and_writes_nothing(
        self,
        wd,
        monkeypatch,
        no_config,
    ):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        target = wd / "newdir"
        code, lines, err = self._run(
            dry_run=True,
            yes=False,
            only="ensure-working-dir",
            no_backup=False,
            backup_dir=None,
            working_dir=target,
        )
        assert code == 0
        assert any("Planned operations" in line for line in lines)
        assert any("[ensure-working-dir]" in line for line in lines)
        assert any("(dry-run" in line for line in lines)
        assert not target.exists()

    def test_confirm_declined_aborts(self, wd, monkeypatch, no_config):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        target = wd / "newdir"
        code, lines, err = self._run(
            dry_run=False,
            yes=False,
            only="ensure-working-dir",
            no_backup=False,
            backup_dir=None,
            working_dir=target,
            confirm_fn=lambda msg: False,
        )
        assert code == 0
        assert any("Aborted" in line for line in lines)
        assert not target.exists()

    def test_apply_creates_dir_and_backup_session(
        self,
        wd,
        monkeypatch,
        no_config,
    ):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        target = wd / "newdir"
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only="ensure-working-dir",
            no_backup=False,
            backup_dir=None,
            working_dir=target,
        )
        assert code == 0
        assert target.is_dir()
        assert any("Done." in line for line in lines)
        assert any(line.startswith("Backup session:") for line in lines)
        backups = list((target / dfr.BACKUP_SUBDIR).iterdir())
        assert len(backups) == 1
        meta = json.loads((backups[0] / "meta.json").read_text())
        assert meta["fix_ids"] == ["ensure-working-dir"]

    def test_no_backup_warning(self, wd, monkeypatch, no_config):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        target = wd / "newdir"
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only="ensure-working-dir",
            no_backup=True,
            backup_dir=None,
            working_dir=target,
        )
        assert code == 0
        assert target.is_dir()
        assert any("--no-backup" in e for e in err)
        assert not (target / dfr.BACKUP_SUBDIR).exists()

    def test_backup_dir_outside_wd_rejected(self, wd, tmp_path, monkeypatch):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        ws = wd / "ws"
        ws.mkdir()
        cfg = _Cfg({"a": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        monkeypatch.setattr(
            dfr,
            "reconcile_workspace_manifest",
            lambda w: None,
        )
        monkeypatch.setattr(
            dfr,
            "get_workspace_skill_manifest_path",
            lambda w: w / "skill.json",
        )
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only="reconcile-workspace-skills",
            no_backup=False,
            backup_dir=tmp_path / "outside",
            working_dir=wd,
        )
        # backup dir missing -> error before writes
        assert code == 1
        assert any("backup base directory missing" in e for e in err)

    def test_apply_error_mid_plan_returns_1(self, wd, monkeypatch, no_config):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())

        def boom_plan(fix_ids, wd_, yes, *, dry_run=False, no_backup=False):
            return [], [
                dfr.PlannedFix(
                    "x",
                    "explode",
                    (),
                    lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                ),
            ]

        monkeypatch.setattr(dfr, "_plan_fixes", boom_plan)
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only=None,
            no_backup=True,
            backup_dir=None,
            working_dir=wd,
        )
        assert code == 1
        assert any("Stopped after error" in e for e in err)

    def test_mkdir_wd_apply_error_returns_1(self, wd, monkeypatch, no_config):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())

        def boom_plan(fix_ids, wd_, yes, *, dry_run=False, no_backup=False):
            return [], [
                dfr.PlannedFix(
                    "ensure-working-dir",
                    "explode during mkdir",
                    (),
                    lambda: (_ for _ in ()).throw(OSError("mkdir failed")),
                ),
            ]

        monkeypatch.setattr(dfr, "_plan_fixes", boom_plan)
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only=None,
            no_backup=True,
            backup_dir=None,
            working_dir=wd,
        )
        assert code == 1
        assert any("Stopped after error" in e for e in err)

    def test_wd_still_missing_after_mkdir(self, wd, monkeypatch, no_config):
        monkeypatch.setattr(dfr, "load_config", lambda: _EmptyCfg())
        target = wd / "newdir"

        def noop_plan(fix_ids, wd_, yes, *, dry_run=False, no_backup=False):
            return [], [
                dfr.PlannedFix(
                    "ensure-working-dir",
                    "pretend mkdir",
                    (),
                    lambda: None,
                ),
            ]

        monkeypatch.setattr(dfr, "_plan_fixes", noop_plan)
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only=None,
            no_backup=True,
            backup_dir=None,
            working_dir=target,
        )
        assert code == 1
        assert any("still missing" in e for e in err)

    def test_backup_dir_outside_working_dir_rejected(
        self,
        wd,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws"
        ws.mkdir()
        (ws / "skill.json").write_text("{}")
        cfg = _Cfg({"a": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        monkeypatch.setattr(
            dfr,
            "reconcile_workspace_manifest",
            lambda w: None,
        )
        monkeypatch.setattr(
            dfr,
            "get_workspace_skill_manifest_path",
            lambda w: w / "skill.json",
        )
        outside = tmp_path / "outside_bkp"
        outside.mkdir()
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only="reconcile-workspace-skills",
            no_backup=False,
            backup_dir=outside,
            working_dir=wd,
        )
        assert code == 1
        assert any("must be inside the working directory" in e for e in err)

    def test_disallowed_backup_path_rejected_mid_apply(
        self,
        wd,
        monkeypatch,
    ):
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws"
        ws.mkdir()
        (ws / "agent.json").write_text("{invalid")
        cfg = _Cfg({"a": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        real_guard = dfr.path_allowed_for_write

        def selective_guard(target, root):
            # allow plan-time checks, refuse during run_doctor_fix backup loop
            if Path(target).name == "agent.json":
                return False
            return real_guard(target, root)

        monkeypatch.setattr(dfr, "path_allowed_for_write", selective_guard)
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only="reset-invalid-agent-json",
            no_backup=False,
            backup_dir=None,
            working_dir=wd,
        )
        assert code == 1
        assert any("refusing to touch disallowed path" in e for e in err)

    def test_backup_of_file_then_write(self, wd, monkeypatch):
        """reset-invalid-agent-json end-to-end: backup written, file reset."""
        monkeypatch.setattr(
            dfr,
            "strict_validate_config_file",
            lambda: (True, "ok"),
        )
        ws = wd / "ws"
        ws.mkdir()
        bad = ws / "agent.json"
        bad.write_text("{invalid")
        cfg = _Cfg({"a": _Ref(str(ws))})
        monkeypatch.setattr(dfr, "load_config", lambda: cfg)
        code, lines, err = self._run(
            dry_run=False,
            yes=True,
            only="reset-invalid-agent-json",
            no_backup=False,
            backup_dir=None,
            working_dir=wd,
        )
        assert code == 0
        sessions = list((wd / dfr.BACKUP_SUBDIR).iterdir())
        assert len(sessions) == 1
        backed = sessions[0] / "files" / "ws" / "agent.json"
        assert backed.read_text() == "{invalid"
        meta = json.loads((sessions[0] / "meta.json").read_text())
        # The runner records native separators (ws\\agent.json on Windows).
        assert [
            Path(rel).as_posix() for rel in meta["backed_up_files_relative"]
        ] == ["ws/agent.json"]
        reset = json.loads(bad.read_text())
        assert reset["id"] == "a"

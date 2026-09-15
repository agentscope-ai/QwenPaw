# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Unit tests for the interactive `init` CLI command."""

import json

import pytest
from click.testing import CliRunner

from qwenpaw.cli import init_cmd as init_mod
from qwenpaw.config import utils as config_utils


@pytest.fixture()
def init_env(monkeypatch, tmp_path):
    """Isolate init_cmd from the real working dir and from heavy side effects.

    Both modules bind ``WORKING_DIR`` by value at import time, so patching the
    constant module alone would not redirect ``get_config_path()``.
    """
    working = tmp_path / "workdir"
    working.mkdir()
    monkeypatch.setattr(init_mod, "WORKING_DIR", working)
    monkeypatch.setattr(config_utils, "WORKING_DIR", working)

    # Reset the module-level config cache so save_config/load_config in one
    # test cannot leak into the next one.
    monkeypatch.setattr(config_utils, "_config_cache", None)
    monkeypatch.setattr(config_utils, "_config_mtime", None)

    calls = {"telemetry_uploads": 0, "opted_out_marks": 0}

    # Telemetry helpers are imported lazily inside init_cmd, so patch the
    # source module rather than the init_cmd namespace.
    from qwenpaw.utils import telemetry as telemetry_mod

    monkeypatch.setattr(
        telemetry_mod, "is_telemetry_opted_out", lambda _wd: False
    )
    monkeypatch.setattr(
        telemetry_mod, "has_telemetry_been_collected", lambda _wd: False
    )

    def _fake_upload(_wd):
        calls["telemetry_uploads"] += 1
        return True

    def _fake_mark(_wd, opted_out=False):
        calls["opted_out_marks"] += 1

    monkeypatch.setattr(
        telemetry_mod, "collect_and_upload_telemetry", _fake_upload
    )
    monkeypatch.setattr(telemetry_mod, "mark_telemetry_collected", _fake_mark)

    # Migration helpers are imported lazily from qwenpaw.app.migration.
    from qwenpaw.app import migration as migration_mod

    migration_calls = []
    for name in (
        "ensure_default_agent_exists",
        "ensure_qa_agent_exists",
        "migrate_legacy_skills_to_skill_pool",
    ):
        monkeypatch.setattr(
            migration_mod,
            name,
            lambda _n=name: migration_calls.append(_n),
        )

    # Skill pool bootstrap is imported lazily from qwenpaw.agents.skill_system.
    from qwenpaw.agents import skill_system as skill_mod

    monkeypatch.setattr(
        skill_mod, "ensure_skill_pool_initialized", lambda: True
    )
    monkeypatch.setattr(
        init_mod, "_sync_default_workspace_skills", lambda _ws, **_kw: 0
    )

    # copy_md_files is imported lazily from qwenpaw.agents.utils.
    from qwenpaw.agents import utils as agents_utils

    copied_md = []
    monkeypatch.setattr(
        agents_utils, "copy_md_files", lambda *_a, **_kw: list(copied_md)
    )

    # ProviderManager is imported at module scope, so patch it on init_cmd.
    class _FakeProviderManager:
        def __init__(self, active):
            self._active = active

        def get_active_model(self):
            return self._active

    monkeypatch.setattr(
        init_mod,
        "ProviderManager",
        type(
            "PM",
            (),
            {"get_instance": staticmethod(lambda: _FakeProviderManager(None))},
        ),
    )

    # Interactive configurators are imported at module scope.
    interactive = []
    for name in (
        "configure_channels_interactive",
        "configure_env_interactive",
        "configure_providers_interactive",
        "configure_skills_interactive",
    ):
        monkeypatch.setattr(
            init_mod,
            name,
            lambda *a, _n=name, **kw: interactive.append((_n, a, kw)),
        )

    # Rich panels write ANSI escapes that make output assertions brittle.
    monkeypatch.setattr(init_mod, "_echo_security_warning_box", lambda: None)
    monkeypatch.setattr(init_mod, "_echo_telemetry_info_box", lambda: None)

    return {
        "working": working,
        "config_path": working / "config.json",
        "heartbeat_path": working / "HEARTBEAT.md",
        "calls": calls,
        "migration_calls": migration_calls,
        "interactive": interactive,
        "copied_md": copied_md,
    }


class TestDefaultsPath:
    """`--defaults --accept-security` must run fully non-interactively."""

    def test_creates_config_and_heartbeat_without_prompting(self, init_env):
        result = CliRunner().invoke(
            init_mod.init_cmd,
            ["--defaults", "--accept-security"],
        )

        assert result.exit_code == 0, result.output
        assert init_env["config_path"].is_file()
        assert init_env["heartbeat_path"].is_file()
        assert "Initialization complete!" in result.output

    def test_defaults_assumes_security_acceptance(self, init_env):
        result = CliRunner().invoke(
            init_mod.init_cmd,
            ["--defaults", "--accept-security"],
        )

        assert result.exit_code == 0, result.output
        assert "Security acceptance assumed" in result.output

    def test_defaults_uses_default_heartbeat_interval_and_target(
        self, init_env
    ):
        CliRunner().invoke(
            init_mod.init_cmd,
            ["--defaults", "--accept-security"],
        )

        saved = json.loads(init_env["config_path"].read_text(encoding="utf-8"))
        # save_config serializes with by_alias=True, so keys are camelCase.
        heartbeat = saved["agents"]["defaults"]["heartbeat"]
        assert heartbeat["every"] == "6h"
        assert heartbeat["target"] == "main"
        assert heartbeat["activeHours"] is None

    def test_defaults_leaves_active_hours_unset(self, init_env):
        CliRunner().invoke(
            init_mod.init_cmd,
            ["--defaults", "--accept-security"],
        )

        saved = json.loads(init_env["config_path"].read_text(encoding="utf-8"))
        assert saved["agents"]["defaults"]["heartbeat"]["activeHours"] is None

    def test_defaults_enables_show_tool_details(self, init_env):
        CliRunner().invoke(
            init_mod.init_cmd,
            ["--defaults", "--accept-security"],
        )

        saved = json.loads(init_env["config_path"].read_text(encoding="utf-8"))
        assert saved["show_tool_details"] is True

    def test_defaults_writes_chinese_heartbeat_checklist(self, init_env):
        CliRunner().invoke(
            init_mod.init_cmd,
            ["--defaults", "--accept-security"],
        )

        content = init_env["heartbeat_path"].read_text(encoding="utf-8")
        assert content == init_mod.DEFAULT_HEARTBEAT_MDS["zh"].strip()

    def test_defaults_runs_migration_steps_in_order(self, init_env):
        CliRunner().invoke(
            init_mod.init_cmd,
            ["--defaults", "--accept-security"],
        )

        assert init_env["migration_calls"] == [
            "ensure_default_agent_exists",
            "migrate_legacy_skills_to_skill_pool",
            "ensure_qa_agent_exists",
        ]

    def test_defaults_uploads_telemetry_without_prompting(self, init_env):
        CliRunner().invoke(
            init_mod.init_cmd,
            ["--defaults", "--accept-security"],
        )

        assert init_env["calls"]["telemetry_uploads"] == 1
        assert init_env["calls"]["opted_out_marks"] == 0

    def test_defaults_creates_missing_working_dir(self, init_env, monkeypatch):
        """The working dir may not exist yet on a freshly mounted volume."""
        missing = init_env["working"].parent / "not-created-yet"
        monkeypatch.setattr(init_mod, "WORKING_DIR", missing)
        monkeypatch.setattr(config_utils, "WORKING_DIR", missing)

        result = CliRunner().invoke(
            init_mod.init_cmd,
            ["--defaults", "--accept-security"],
        )

        assert result.exit_code == 0, result.output
        assert missing.is_dir()
        assert (missing / "config.json").is_file()

# -*- coding: utf-8 -*-
"""Tests for channels CLI list/configure commands.

Covers list_cmd (empty config, enabled/disabled rendering, extra
pydantic channels) and configure_cmd (interactive-config save-back and
error handling), which were previously untested.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import qwenpaw.cli.channels_cmd as cc


def _agent_config(channels=None):
    return SimpleNamespace(channels=channels)


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# list_cmd
# ---------------------------------------------------------------------------


class TestListCmd:
    def test_load_failure_reports_error(self, runner, monkeypatch):
        def boom(agent_id):
            raise ValueError("config missing")

        monkeypatch.setattr(cc, "load_agent_config", boom)
        result = runner.invoke(cc.list_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_no_channels_configured(self, runner, monkeypatch):
        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda agent_id: _agent_config(None),
        )
        result = runner.invoke(cc.list_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 0
        assert "No channels configured" in result.output

    def test_enabled_channel_rendered(self, runner, monkeypatch):
        channels = SimpleNamespace(
            console=SimpleNamespace(enabled=True, mode="local"),
        )
        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda agent_id: _agent_config(channels),
        )
        monkeypatch.setattr(
            cc,
            "_get_channel_names",
            lambda: {"console": "Console"},
        )
        result = runner.invoke(cc.list_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 0
        assert "Console" in result.output
        assert "enabled" in result.output

    def test_disabled_channel_rendered(self, runner, monkeypatch):
        channels = SimpleNamespace(
            console=SimpleNamespace(enabled=False),
        )
        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda agent_id: _agent_config(channels),
        )
        monkeypatch.setattr(
            cc,
            "_get_channel_names",
            lambda: {"console": "Console"},
        )
        result = runner.invoke(cc.list_cmd, ["--agent-id", "a1"])
        assert "disabled" in result.output

    def test_secret_fields_masked(self, runner, monkeypatch):
        channels = SimpleNamespace(
            console=SimpleNamespace(
                enabled=True,
                client_secret="supersecretkey",
            ),
        )
        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda agent_id: _agent_config(channels),
        )
        monkeypatch.setattr(
            cc,
            "_get_channel_names",
            lambda: {"console": "Console"},
        )
        result = runner.invoke(cc.list_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 0
        # raw secret must not leak into output
        assert "supersecretkey" not in result.output
        assert "****" in result.output

    def test_non_secret_fields_shown(self, runner, monkeypatch):
        channels = SimpleNamespace(
            console=SimpleNamespace(enabled=True, mode="local"),
        )
        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda agent_id: _agent_config(channels),
        )
        monkeypatch.setattr(
            cc,
            "_get_channel_names",
            lambda: {"console": "Console"},
        )
        result = runner.invoke(cc.list_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 0
        assert "local" in result.output

    def test_extra_pydantic_channel_included(self, runner, monkeypatch):
        channels = SimpleNamespace(
            console=None,
            __pydantic_extra__={
                "custom": {"enabled": True, "url": "http://x"},
            },
        )
        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda agent_id: _agent_config(channels),
        )
        monkeypatch.setattr(
            cc,
            "_get_channel_names",
            lambda: {"custom": "Custom"},
        )
        result = runner.invoke(cc.list_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 0
        assert "Custom" in result.output

    def test_unknown_channel_key_skipped(self, runner, monkeypatch):
        channels = SimpleNamespace(console=None)
        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda agent_id: _agent_config(channels),
        )
        monkeypatch.setattr(
            cc,
            "_get_channel_names",
            lambda: {"nonexistent": "X"},
        )
        result = runner.invoke(cc.list_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# configure_cmd
# ---------------------------------------------------------------------------


class TestConfigureCmd:
    def test_saves_interactive_result(self, runner, monkeypatch):
        original_channels = SimpleNamespace(
            console=SimpleNamespace(enabled=False),
        )
        saved = {}

        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda agent_id: _agent_config(original_channels),
        )
        monkeypatch.setattr(
            cc,
            "configure_channels_interactive",
            lambda config: None,
        )

        def fake_save(agent_id, config):
            saved["agent_id"] = agent_id
            saved["channels"] = config.channels

        monkeypatch.setattr(cc, "save_agent_config", fake_save)
        result = runner.invoke(cc.configure_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 0
        assert "Configuration saved" in result.output
        assert saved["agent_id"] == "a1"
        assert saved["channels"] is original_channels

    def test_none_channels_falls_back_to_default(self, runner, monkeypatch):
        captured = {}

        monkeypatch.setattr(
            cc,
            "load_agent_config",
            lambda agent_id: _agent_config(None),
        )

        def fake_configure(config):
            captured["channels"] = config.channels

        monkeypatch.setattr(
            cc,
            "configure_channels_interactive",
            fake_configure,
        )
        monkeypatch.setattr(cc, "save_agent_config", lambda a, c: None)
        result = runner.invoke(cc.configure_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 0
        # a channels object must exist even when the agent had none
        assert captured["channels"] is not None

    def test_value_error_reports_and_exits_1(self, runner, monkeypatch):
        def boom(agent_id):
            raise ValueError("bad config")

        monkeypatch.setattr(cc, "load_agent_config", boom)
        result = runner.invoke(cc.configure_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_app_exception_reports_and_exits_1(self, runner, monkeypatch):
        from qwenpaw.exceptions import AppBaseException

        def boom(agent_id):
            raise AppBaseException(message="boom")

        monkeypatch.setattr(cc, "load_agent_config", boom)
        result = runner.invoke(cc.configure_cmd, ["--agent-id", "a1"])
        assert result.exit_code == 1
        assert "Error" in result.output

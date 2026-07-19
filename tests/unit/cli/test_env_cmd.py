# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw env`` CLI surface."""

from __future__ import annotations

import json

from click.testing import CliRunner

from qwenpaw.cli import env_cmd


def test_env_list_json_outputs_sorted_mapping(monkeypatch) -> None:
    monkeypatch.setattr(
        env_cmd,
        "load_envs",
        lambda: {"ZEBRA_TOKEN": "last", "ALPHA_TOKEN": "first"},
    )

    result = CliRunner().invoke(env_cmd.env_group, ["list", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "ALPHA_TOKEN": "first",
        "ZEBRA_TOKEN": "last",
    }
    assert result.output.index("ALPHA_TOKEN") < result.output.index(
        "ZEBRA_TOKEN",
    )


def test_env_list_json_outputs_empty_object(monkeypatch) -> None:
    monkeypatch.setattr(env_cmd, "load_envs", lambda: {})

    result = CliRunner().invoke(env_cmd.env_group, ["list", "--json"])

    assert result.exit_code == 0
    assert result.output == "{}\n"


def test_env_get_outputs_raw_value(monkeypatch) -> None:
    monkeypatch.setattr(
        env_cmd,
        "load_envs",
        lambda: {"SERVICE_TOKEN": "value with spaces"},
    )

    result = CliRunner().invoke(
        env_cmd.env_group,
        ["get", "SERVICE_TOKEN"],
    )

    assert result.exit_code == 0
    assert result.output == "value with spaces\n"


def test_env_get_missing_key_exits_nonzero(monkeypatch) -> None:
    monkeypatch.setattr(env_cmd, "load_envs", lambda: {})

    result = CliRunner().invoke(env_cmd.env_group, ["get", "MISSING_TOKEN"])

    assert result.exit_code == 1
    assert "Env var 'MISSING_TOKEN' not found." in result.output

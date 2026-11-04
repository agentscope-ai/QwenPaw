# -*- coding: utf-8 -*-
"""`qwenpaw env list` / `env set` must not print secret values by default."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from qwenpaw.cli import env_cmd


@pytest.fixture(name="fake_envs")
def fixture_fake_envs(monkeypatch):
    monkeypatch.setattr(
        env_cmd,
        "load_envs",
        lambda: {"MY_SECRET": "s3cr3t-value-1234"},
    )
    monkeypatch.setattr(env_cmd, "_managed_envs", lambda *args, **kwargs: None)


def test_list_masks_values_by_default(fake_envs):
    result = CliRunner().invoke(env_cmd.env_group, ["list"])
    assert result.exit_code == 0
    assert "MY_SECRET" in result.output
    assert "s3cr3t-value-1234" not in result.output
    assert "s3cr***34" in result.output


def test_list_reveal_prints_plaintext(fake_envs):
    result = CliRunner().invoke(env_cmd.env_group, ["list", "--reveal"])
    assert result.exit_code == 0
    assert "s3cr3t-value-1234" in result.output


def test_set_masks_echoed_value(monkeypatch):
    monkeypatch.setattr(env_cmd, "set_env_var", lambda key, value: None)
    monkeypatch.setattr(env_cmd, "validate_env_key", lambda key: None)
    monkeypatch.setattr(env_cmd, "validate_env_value", lambda key, value: None)

    result = CliRunner().invoke(
        env_cmd.env_group,
        ["set", "MY_SECRET", "s3cr3t-value-1234"],
    )

    assert result.exit_code == 0
    assert "s3cr3t-value-1234" not in result.output
    assert "s3cr***34" in result.output


def test_mask_value_helper():
    assert env_cmd._mask_value("") == ""
    assert env_cmd._mask_value("short") == "*****"
    assert env_cmd._mask_value("s3cr3t-value-1234") == "s3cr***34"

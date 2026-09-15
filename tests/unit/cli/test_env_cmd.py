# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Unit tests for the `env` CLI group (list / set / delete)."""

import json

import pytest
from click.testing import CliRunner

from qwenpaw.cli import env_cmd as env_mod
from qwenpaw.envs import store as env_store


@pytest.fixture()
def env_file(monkeypatch, tmp_path):
    """Point the env store at a temp file so no real secret dir is touched."""
    path = tmp_path / "envs.json"
    monkeypatch.setattr(env_store, "_ENVS_JSON", path)
    monkeypatch.setattr(env_store, "_LEGACY_ENVS_JSON_CANDIDATES", ())
    return path


def _seed(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


class TestListCmd:
    def test_reports_when_no_variables_configured(self, env_file):
        result = CliRunner().invoke(env_mod.env_group, ["list"])

        assert result.exit_code == 0
        assert "No environment variables configured." in result.output

    def test_lists_keys_in_sorted_order(self, env_file):
        _seed(env_file, {"ZEBRA": "z", "ALPHA": "a", "MIDDLE": "m"})

        result = CliRunner().invoke(env_mod.env_group, ["list"])

        assert result.exit_code == 0
        positions = [
            result.output.index("ALPHA"),
            result.output.index("MIDDLE"),
            result.output.index("ZEBRA"),
        ]
        assert positions == sorted(positions)

    def test_shows_key_and_value_columns(self, env_file):
        _seed(env_file, {"MY_KEY": "my-value"})

        result = CliRunner().invoke(env_mod.env_group, ["list"])

        assert result.exit_code == 0
        assert "MY_KEY" in result.output
        assert "my-value" in result.output


class TestSetCmd:
    def test_persists_key_and_confirms(self, env_file):
        result = CliRunner().invoke(env_mod.env_group, ["set", "MY_KEY", "v1"])

        assert result.exit_code == 0
        assert "MY_KEY" in result.output
        assert env_file.is_file()
        # Values are encrypted at rest (ENC:...), so assert via load_envs().
        assert env_mod.load_envs()["MY_KEY"] == "v1"

    def test_overwrites_existing_value(self, env_file):
        _seed(env_file, {"MY_KEY": "old"})

        result = CliRunner().invoke(
            env_mod.env_group, ["set", "MY_KEY", "new"]
        )

        assert result.exit_code == 0
        assert env_mod.load_envs()["MY_KEY"] == "new"

    def test_rejects_malformed_key_with_click_exception(self, env_file):
        result = CliRunner().invoke(
            env_mod.env_group, ["set", "not a key!", "v"]
        )

        assert result.exit_code != 0
        assert "Invalid environment variable name" in result.output

    def test_rejects_lowercase_qwenpaw_key(self, env_file):
        result = CliRunner().invoke(
            env_mod.env_group, ["set", "qwenpaw_lower", "v"]
        )

        assert result.exit_code != 0
        assert "must be uppercase" in result.output

    def test_rejects_internally_managed_key(self, env_file):
        result = CliRunner().invoke(
            env_mod.env_group,
            ["set", "QWENPAW_RUNTIME_INTERNAL_TOKEN", "secret"],
        )

        assert result.exit_code != 0
        assert "managed internally" in result.output

    def test_rejects_read_only_known_key(self, env_file):
        """QWENPAW_WORKING_DIR is a known non-editable spec, not internal."""
        result = CliRunner().invoke(
            env_mod.env_group,
            ["set", "QWENPAW_WORKING_DIR", "/tmp/x"],
        )

        assert result.exit_code != 0
        assert "read-only" in result.output

    def test_validation_failure_does_not_persist(self, env_file):
        CliRunner().invoke(env_mod.env_group, ["set", "bad key", "v"])

        assert "bad key" not in env_mod.load_envs()


class TestDeleteCmd:
    def test_deletes_existing_key(self, env_file):
        _seed(env_file, {"KEEP": "1", "GONE": "2"})

        result = CliRunner().invoke(env_mod.env_group, ["delete", "GONE"])

        assert result.exit_code == 0
        assert "Deleted" in result.output
        saved = env_mod.load_envs()
        assert "GONE" not in saved
        assert saved["KEEP"] == "1"

    def test_unknown_key_exits_nonzero_and_reports(self, env_file):
        _seed(env_file, {"KEEP": "1"})

        result = CliRunner().invoke(env_mod.env_group, ["delete", "MISSING"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_unknown_key_leaves_store_untouched(self, env_file):
        _seed(env_file, {"KEEP": "1"})

        CliRunner().invoke(env_mod.env_group, ["delete", "MISSING"])

        assert env_mod.load_envs() == {"KEEP": "1"}

    def test_delete_on_empty_store_reports_not_found(self, env_file):
        result = CliRunner().invoke(env_mod.env_group, ["delete", "ANY"])

        assert result.exit_code == 1
        assert "not found" in result.output

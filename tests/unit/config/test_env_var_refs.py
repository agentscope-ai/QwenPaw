# -*- coding: utf-8 -*-
"""Environment variable references in JSON config data."""

import json

from qwenpaw.config.utils import expand_env_var_refs, load_config


def test_expand_env_var_refs_recursively(monkeypatch):
    monkeypatch.setenv("QWENPAW_TEST_SECRET", "resolved-secret")

    data = {
        "plain": "keep ${QWENPAW_TEST_SECRET}",
        "secret": "${QWENPAW_TEST_SECRET}",
        "nested": [{"token": "${QWENPAW_TEST_SECRET}"}],
    }

    assert expand_env_var_refs(data) == {
        "plain": "keep ${QWENPAW_TEST_SECRET}",
        "secret": "resolved-secret",
        "nested": [{"token": "resolved-secret"}],
    }


def test_expand_env_var_refs_keeps_unset_placeholders(caplog):
    data = {"secret": "${QWENPAW_UNSET_SECRET}"}

    assert expand_env_var_refs(data) == data
    assert "QWENPAW_UNSET_SECRET" in caplog.text


def test_load_config_expands_env_var_refs(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_TEST_TIMEZONE", "Asia/Shanghai")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"user_timezone": "${QWENPAW_TEST_TIMEZONE}"}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.user_timezone == "Asia/Shanghai"

# -*- coding: utf-8 -*-
"""Unit tests for ``_resolve_env_vars`` in config/utils.py."""

from __future__ import annotations

import os

from qwenpaw.config.utils import _resolve_env_vars


def test_resolves_single_env_var():
    os.environ["TEST_VAR_A"] = "resolved-a"
    try:
        data = {"api_key": "${TEST_VAR_A}"}
        result = _resolve_env_vars(data)
        assert result == {"api_key": "resolved-a"}
    finally:
        del os.environ["TEST_VAR_A"]


def test_leaves_non_placeholder_strings():
    data = {"name": "plain-text", "host": "127.0.0.1"}
    assert _resolve_env_vars(data) == {
        "name": "plain-text",
        "host": "127.0.0.1",
    }


def test_leaves_non_string_values():
    data = {"port": 8080, "enabled": True, "tags": ["a", "b"]}
    assert _resolve_env_vars(data) == {
        "port": 8080,
        "enabled": True,
        "tags": ["a", "b"],
    }


def test_keeps_placeholder_when_env_var_missing():
    os.environ.pop("MISSING_VAR_XYZ", None)
    data = {"token": "${MISSING_VAR_XYZ}"}
    assert _resolve_env_vars(data) == {"token": "${MISSING_VAR_XYZ}"}


def test_resolves_nested_dict_values():
    os.environ["TEST_NESTED"] = "nested-val"
    try:
        data = {
            "channel": {
                "discord": {"bot_token": "${TEST_NESTED}"},
                "feishu": {"app_secret": "plain"},
            },
        }
        result = _resolve_env_vars(data)
        assert result["channel"]["discord"]["bot_token"] == "nested-val"
        assert result["channel"]["feishu"]["app_secret"] == "plain"
    finally:
        del os.environ["TEST_NESTED"]


def test_resolves_list_values():
    os.environ["TEST_LIST"] = "list-val"
    try:
        data = {"tokens": ["${TEST_LIST}", "static"]}
        result = _resolve_env_vars(data)
        assert result == {"tokens": ["list-val", "static"]}
    finally:
        del os.environ["TEST_LIST"]


def test_does_not_resolve_env_var_in_dict_key():
    os.environ["KEY_VAR"] = "should-not-work"
    try:
        data = {"${KEY_VAR}": "value"}
        result = _resolve_env_vars(data)
        assert result == {"${KEY_VAR}": "value"}
    finally:
        del os.environ["KEY_VAR"]


def test_multiple_placeholders_in_one_string():
    os.environ["HOST"] = "localhost"
    os.environ["PORT"] = "5432"
    try:
        data = {"url": "postgres://${HOST}:${PORT}/db"}
        result = _resolve_env_vars(data)
        assert result == {"url": "postgres://localhost:5432/db"}
    finally:
        del os.environ["HOST"]
        del os.environ["PORT"]

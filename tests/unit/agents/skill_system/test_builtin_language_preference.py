# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Builtin skill language preference unit tests.

Regression coverage:
- GitHub issue #3688: builtin skill descriptions must respect the language
  setting (builtin_skill_language / UI language).
"""

from __future__ import annotations

import json

import pytest
from qwenpaw.agents.skill_system import registry as skill_registry


@pytest.fixture(autouse=True)
def _clear_builtin_cache():
    """registry caches language preference globally; reset per test."""
    skill_registry._builtin_cache.clear()
    yield
    skill_registry._builtin_cache.clear()


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"builtin_skill_language": "zh"}, "zh"),
        ({"builtin_skill_language": "en"}, "en"),
        ({"builtin_skill_language": "ZH"}, "zh"),
        ({"language": "zh-CN"}, "zh"),
        ({"language": "en-US"}, "en"),
        ({}, "en"),
    ],
)
def test_language_preference_from_settings(
    tmp_path,
    monkeypatch,
    settings,
    expected,
):
    """#3688: language setting must drive builtin skill language."""
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps(settings),
        encoding="utf-8",
    )
    assert skill_registry.get_builtin_skill_language_preference() == expected


def test_missing_settings_file_defaults_to_en(tmp_path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    assert skill_registry.get_builtin_skill_language_preference() == "en"


def test_malformed_settings_json_defaults_to_en(tmp_path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert skill_registry.get_builtin_skill_language_preference() == "en"

"""Builtin skill language preference unit tests.

Regression scope (后端单测缺口补齐第 1 批，A 档)：
- GitHub issue #3688: 内置技能描述必须尊重语言设置（builtin_skill_language / UI language）

出处：泰哥 2026-08-23 批复后端单测缺口补齐计划第 1 批。
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
    """#3688：语言设置必须传导到内置技能语言选择。"""
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

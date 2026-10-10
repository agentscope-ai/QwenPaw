# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument,unused-import  # noqa: E501
"""Pure-logic unit tests for skill_system/registry.py helpers.

Coverage-driven backfill (batch 3, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: builtin-skill language
normalisation, packaged-name parsing, and the skill-config environment
variable override machinery, which previously sat at ~38% coverage.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import registry as skill_registry


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_caches(monkeypatch):
    """Isolate the module-level caches and env entries per test."""
    monkeypatch.setattr(skill_registry, "_builtin_cache", {})
    monkeypatch.setattr(skill_registry, "_ACTIVE_SKILL_ENV_ENTRIES", {})
    # Snapshot any env vars we may touch so we can restore.
    snapshot = {
        key: os.environ.get(key)
        for key in list(os.environ)
        if key.startswith("QWENPAW_SKILL_CONFIG_")
    }
    yield
    for key in list(os.environ):
        if key.startswith("QWENPAW_SKILL_CONFIG_"):
            prior = snapshot.get(key)
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


@pytest.fixture()
def fake_working_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# _normalize_builtin_skill_language
# ---------------------------------------------------------------------------


class TestNormalizeBuiltinSkillLanguage:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("en", "en"),
            ("zh", "zh"),
            ("EN", "en"),
            ("  Zh  ", "zh"),
        ],
    )
    def test_known_languages(self, raw, expected):
        assert (
            skill_registry._normalize_builtin_skill_language(raw) == expected
        )

    @pytest.mark.parametrize("raw", ["", None, "fr", "de", "unknown"])
    def test_unknown_falls_back_to_en(self, raw):
        assert skill_registry._normalize_builtin_skill_language(raw) == "en"

    def test_empty_fallback_returns_empty(self):
        assert (
            skill_registry._normalize_builtin_skill_language(
                "fr",
                fallback="",
            )
            == ""
        )

    def test_known_fallback_respected(self):
        assert (
            skill_registry._normalize_builtin_skill_language(
                "fr",
                fallback="zh",
            )
            == "zh"
        )


# ---------------------------------------------------------------------------
# language preference caching
# ---------------------------------------------------------------------------


class TestBuiltinLanguagePreference:
    def test_set_and_get(self, clean_caches):
        skill_registry.set_builtin_skill_language_preference("zh")
        assert skill_registry.get_builtin_skill_language_preference() == "zh"

    def test_set_normalizes(self, clean_caches):
        skill_registry.set_builtin_skill_language_preference("ZH")
        assert skill_registry.get_builtin_skill_language_preference() == "zh"

    def test_set_unknown_falls_back_to_en(self, clean_caches):
        skill_registry.set_builtin_skill_language_preference("fr")
        assert skill_registry.get_builtin_skill_language_preference() == "en"

    def test_reads_settings_explicit(self, clean_caches, fake_working_dir):
        (fake_working_dir / "settings.json").write_text(
            json.dumps({"builtin_skill_language": "zh"}),
            encoding="utf-8",
        )
        assert skill_registry.get_builtin_skill_language_preference() == "zh"

    def test_reads_ui_language_zh(self, clean_caches, fake_working_dir):
        (fake_working_dir / "settings.json").write_text(
            json.dumps({"language": "zh-CN"}),
            encoding="utf-8",
        )
        assert skill_registry.get_builtin_skill_language_preference() == "zh"

    def test_reads_ui_language_default_en(
        self,
        clean_caches,
        fake_working_dir,
    ):
        (fake_working_dir / "settings.json").write_text(
            json.dumps({"language": "en-US"}),
            encoding="utf-8",
        )
        assert skill_registry.get_builtin_skill_language_preference() == "en"

    def test_missing_settings_defaults_en(
        self,
        clean_caches,
        fake_working_dir,
    ):
        assert skill_registry.get_builtin_skill_language_preference() == "en"

    def test_invalid_json_defaults_en(self, clean_caches, fake_working_dir):
        (fake_working_dir / "settings.json").write_text(
            "{not valid json",
            encoding="utf-8",
        )
        assert skill_registry.get_builtin_skill_language_preference() == "en"

    def test_cached_value_reused(self, clean_caches, fake_working_dir):
        # Prime the cache, then change the file — the cached value must win.
        assert skill_registry.get_builtin_skill_language_preference() == "en"
        (fake_working_dir / "settings.json").write_text(
            json.dumps({"builtin_skill_language": "zh"}),
            encoding="utf-8",
        )
        assert skill_registry.get_builtin_skill_language_preference() == "en"


# ---------------------------------------------------------------------------
# packaged builtin name parsing
# ---------------------------------------------------------------------------


class TestParseBuiltinSkillIdentity:
    def test_parses_en_variant(self):
        identity = skill_registry._parse_builtin_skill_identity("browser-en")
        assert identity is not None
        assert identity.name == "browser"
        assert identity.language == "en"
        assert identity.source_name == "browser-en"

    def test_parses_zh_variant(self):
        identity = skill_registry._parse_builtin_skill_identity("search-zh")
        assert identity is not None
        assert identity.name == "search"
        assert identity.language == "zh"

    def test_name_with_hyphens(self):
        identity = skill_registry._parse_builtin_skill_identity(
            "my-skill-zh",
        )
        assert identity is not None
        assert identity.name == "my-skill"
        assert identity.language == "zh"

    @pytest.mark.parametrize("raw", ["", None, "browser", "browser-fr", "en"])
    def test_rejects_non_variant_names(self, raw):
        assert skill_registry._parse_builtin_skill_identity(raw) is None

    def test_strips_whitespace(self):
        identity = skill_registry._parse_builtin_skill_identity("  x-en  ")
        assert identity is not None
        assert identity.name == "x"


class TestCanonicalBuiltinSkillName:
    def test_variant_canonicalised(self):
        assert (
            skill_registry._canonical_builtin_skill_name("browser-en")
            == "browser"
        )

    def test_non_variant_passthrough(self):
        assert (
            skill_registry._canonical_builtin_skill_name("custom") == "custom"
        )

    def test_registry_membership_filter(self):
        registry = {"browser": {}}
        assert (
            skill_registry._canonical_builtin_skill_name(
                "browser-en",
                registry,
            )
            == "browser"
        )
        # Not in registry → keep original form.
        assert (
            skill_registry._canonical_builtin_skill_name(
                "other-en",
                registry,
            )
            == "other-en"
        )


# ---------------------------------------------------------------------------
# env-var override building
# ---------------------------------------------------------------------------


class TestSkillEnvVarName:
    def test_simple_name(self):
        assert (
            skill_registry._skill_config_env_var_name("browser")
            == "QWENPAW_SKILL_CONFIG_BROWSER"
        )

    def test_non_alnum_becomes_underscore(self):
        assert (
            skill_registry._skill_config_env_var_name("my-skill")
            == "QWENPAW_SKILL_CONFIG_MY_SKILL"
        )

    def test_empty_name_fallback(self):
        assert (
            skill_registry._skill_config_env_var_name("")
            == "QWENPAW_SKILL_CONFIG_DEFAULT"
        )

    def test_stringify_values(self):
        assert skill_registry._stringify_skill_env_value("plain") == "plain"
        assert skill_registry._stringify_skill_env_value(5) == "5"
        assert (
            skill_registry._stringify_skill_env_value({"a": 1}) == '{"a": 1}'
        )


class TestBuildSkillConfigEnvOverrides:
    def test_required_keys_exported(self):
        overrides = skill_registry._build_skill_config_env_overrides(
            "demo",
            {"API_KEY": "abc", "extra": 1},
            ["API_KEY"],
        )
        assert overrides["API_KEY"] == "abc"
        assert "extra" not in overrides
        full = json.loads(overrides["QWENPAW_SKILL_CONFIG_DEMO"])
        assert full == {"API_KEY": "abc", "extra": 1}

    def test_missing_required_value_skipped(self):
        overrides = skill_registry._build_skill_config_env_overrides(
            "demo",
            {"API_KEY": ""},
            ["API_KEY"],
        )
        assert "API_KEY" not in overrides

    def test_non_string_value_serialised(self):
        overrides = skill_registry._build_skill_config_env_overrides(
            "demo",
            {"TIMEOUT": 30},
            ["TIMEOUT"],
        )
        assert overrides["TIMEOUT"] == "30"

    def test_blank_require_envs_ignored(self):
        overrides = skill_registry._build_skill_config_env_overrides(
            "demo",
            {"k": "v"},
            ["  ", ""],
        )
        assert list(overrides) == ["QWENPAW_SKILL_CONFIG_DEMO"]


# ---------------------------------------------------------------------------
# env-key acquire / release accounting
# ---------------------------------------------------------------------------


class TestSkillEnvKeyLifecycle:
    KEY = "QWENPAW_SKILL_CONFIG_TEST_KEY"

    def test_acquire_sets_env(self, clean_caches):
        assert skill_registry._acquire_skill_env_key(self.KEY, "v1") is True
        assert os.environ[self.KEY] == "v1"

    def test_double_acquire_same_value_reentrant(self, clean_caches):
        assert skill_registry._acquire_skill_env_key(self.KEY, "v1") is True
        assert skill_registry._acquire_skill_env_key(self.KEY, "v1") is True
        assert skill_registry._ACTIVE_SKILL_ENV_ENTRIES[self.KEY]["count"] == 2

    def test_conflicting_value_rejected(self, clean_caches):
        assert skill_registry._acquire_skill_env_key(self.KEY, "v1") is True
        assert skill_registry._acquire_skill_env_key(self.KEY, "v2") is False
        assert os.environ[self.KEY] == "v1"

    def test_preexisting_env_var_blocks_acquire(self, clean_caches):
        os.environ[self.KEY] = "preexisting"
        assert skill_registry._acquire_skill_env_key(self.KEY, "v1") is False

    def test_release_decrements(self, clean_caches):
        skill_registry._acquire_skill_env_key(self.KEY, "v1")
        skill_registry._acquire_skill_env_key(self.KEY, "v1")
        skill_registry._release_skill_env_key(self.KEY)
        # Still one holder → env preserved.
        assert os.environ[self.KEY] == "v1"
        skill_registry._release_skill_env_key(self.KEY)
        assert self.KEY not in os.environ
        assert self.KEY not in skill_registry._ACTIVE_SKILL_ENV_ENTRIES

    def test_release_unknown_key_is_noop(self, clean_caches):
        skill_registry._release_skill_env_key("QWENPAW_SKILL_CONFIG_NOPE")


# ---------------------------------------------------------------------------
# apply_skill_config_env_overrides context manager
# ---------------------------------------------------------------------------


class TestApplySkillConfigEnvOverrides:
    def test_injects_and_cleans_up(self, clean_caches, tmp_path, monkeypatch):
        manifest = {
            "skills": {
                "demo": {
                    "config": {"API_KEY": "secret"},
                    "requirements": {"require_envs": ["API_KEY"]},
                    "enabled": True,
                    "channels": ["all"],
                },
            },
        }
        monkeypatch.setattr(
            skill_registry,
            "read_skill_manifest",
            lambda workspace_dir: manifest,
        )
        monkeypatch.setattr(
            skill_registry,
            "resolve_effective_skills",
            lambda workspace_dir, channel: ["demo"],
        )

        key = "QWENPAW_SKILL_CONFIG_DEMO"
        with skill_registry.apply_skill_config_env_overrides(
            tmp_path,
            "console",
        ):
            assert os.environ["API_KEY"] == "secret"
            assert key in os.environ
        assert "API_KEY" not in os.environ
        assert key not in os.environ

    def test_skills_without_config_skipped(
        self,
        clean_caches,
        tmp_path,
        monkeypatch,
    ):
        manifest = {
            "skills": {
                "empty": {"config": {}, "requirements": {}},
            },
        }
        monkeypatch.setattr(
            skill_registry,
            "read_skill_manifest",
            lambda workspace_dir: manifest,
        )
        monkeypatch.setattr(
            skill_registry,
            "resolve_effective_skills",
            lambda workspace_dir, channel: ["empty"],
        )
        with skill_registry.apply_skill_config_env_overrides(
            tmp_path,
            "console",
        ):
            assert not [
                k for k in os.environ if k.startswith("QWENPAW_SKILL_CONFIG_")
            ]

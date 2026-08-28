# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for registry builtin-import resolution layer.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the builtin skill
language resolution, import-candidate building, request normalisation
and conflict detection in ``registry.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import registry as reg
from qwenpaw.agents.skill_system.models import BuiltinSkillVariant


@pytest.fixture()
def builtin_registry(tmp_path):
    def _real_variant(name: str, language: str, version_text: str = "1.0"):
        skill_dir = tmp_path / "pkg" / f"{name}-{language}"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            skill_md.write_text(
                f"body of {name} {language}",
                encoding="utf-8",
            )
        return BuiltinSkillVariant(
            name=name,
            language=language,
            source_name=f"{name}-{language}",
            skill_dir=skill_dir,
            skill_md_path=skill_md,
            description=f"{name} ({language})",
            version_text=version_text,
        )

    return {
        "browser": {
            "en": _real_variant("browser", "en", "2.0"),
            "zh": _real_variant("browser", "zh", "2.0"),
        },
        "solo": {
            "en": _real_variant("solo", "en", "1.0"),
        },
    }


# ---------------------------------------------------------------------------
# _resolve_pool_builtin_language
# ---------------------------------------------------------------------------


class TestResolvePoolBuiltinLanguage:
    def test_configured_language_wins(self, builtin_registry):
        entry = {"builtin_language": "zh"}
        assert (
            reg._resolve_pool_builtin_language(
                "browser",
                entry,
                builtin_registry,
            )
            == "zh"
        )

    def test_source_name_identity_fallback(self, builtin_registry):
        entry = {"builtin_source_name": "browser-en"}
        assert (
            reg._resolve_pool_builtin_language(
                "browser",
                entry,
                builtin_registry,
            )
            == "en"
        )

    def test_unknown_skill_returns_empty(self, builtin_registry):
        assert (
            reg._resolve_pool_builtin_language("ghost", {}, builtin_registry)
            == ""
        )

    def test_falls_back_to_preference(self, builtin_registry, monkeypatch):
        monkeypatch.setattr(
            reg,
            "get_builtin_skill_language_preference",
            lambda: "zh",
        )
        monkeypatch.setattr(
            reg,
            "get_skill_pool_dir",
            lambda: Path("/nonexistent/pool"),
        )
        entry = {}
        assert (
            reg._resolve_pool_builtin_language(
                "browser",
                entry,
                builtin_registry,
            )
            == "zh"
        )

    def test_cjk_content_guesses_zh(
        self,
        builtin_registry,
        tmp_path,
        monkeypatch,
    ):
        pool_dir = tmp_path / "pool"
        skill_dir = pool_dir / "browser"
        skill_dir.mkdir(parents=True)
        cjk = "这是一个中文技能说明" * 4  # ≥32 CJK chars
        (skill_dir / "SKILL.md").write_text(cjk, encoding="utf-8")
        monkeypatch.setattr(reg, "get_skill_pool_dir", lambda: pool_dir)
        entry = {}
        assert (
            reg._resolve_pool_builtin_language(
                "browser",
                entry,
                builtin_registry,
            )
            == "zh"
        )

    def test_hash_match_picks_variant(
        self,
        builtin_registry,
        tmp_path,
        monkeypatch,
    ):
        pool_dir = tmp_path / "pool"
        skill_dir = pool_dir / "browser"
        skill_dir.mkdir(parents=True)
        # copy the packaged en variant body so hashes match exactly
        en_body = builtin_registry["browser"]["en"].skill_md_path.read_text(
            encoding="utf-8",
        )
        (skill_dir / "SKILL.md").write_text(en_body, encoding="utf-8")
        monkeypatch.setattr(reg, "get_skill_pool_dir", lambda: pool_dir)
        assert (
            reg._resolve_pool_builtin_language("browser", {}, builtin_registry)
            == "en"
        )


# ---------------------------------------------------------------------------
# _build_builtin_language_spec
# ---------------------------------------------------------------------------


class TestBuildBuiltinLanguageSpec:
    def test_missing_when_no_current(self, builtin_registry):
        spec = reg._build_builtin_language_spec(
            "en",
            builtin_registry["browser"]["en"],
            builtin_registry["browser"],
            {},
        )
        assert spec["status"] == "missing"
        assert spec["version_text"] == "2.0"

    def test_conflict_when_source_not_builtin(self, builtin_registry):
        current = {"source": "customized", "version_text": "2.0"}
        spec = reg._build_builtin_language_spec(
            "en",
            builtin_registry["browser"]["en"],
            builtin_registry["browser"],
            current,
        )
        assert spec["status"] == "conflict"

    def test_current_when_versions_match(self, builtin_registry):
        current = {"source": "builtin", "version_text": "2.0"}
        spec = reg._build_builtin_language_spec(
            "en",
            builtin_registry["browser"]["en"],
            builtin_registry["browser"],
            current,
            current_language="en",
        )
        assert spec["status"] == "current"

    def test_outdated_when_versions_differ(self, builtin_registry):
        current = {"source": "builtin", "version_text": "1.0"}
        spec = reg._build_builtin_language_spec(
            "en",
            builtin_registry["browser"]["en"],
            builtin_registry["browser"],
            current,
            current_language="en",
        )
        assert spec["status"] == "outdated"

    def test_conflict_when_unknown_variant(self, builtin_registry):
        current = {"source": "builtin", "version_text": "9.9"}
        spec = reg._build_builtin_language_spec(
            "zh",
            builtin_registry["browser"]["zh"],
            builtin_registry["browser"],
            current,
            current_language="zz",  # not in variants
        )
        assert spec["status"] == "conflict"


# ---------------------------------------------------------------------------
# _build_builtin_import_candidate
# ---------------------------------------------------------------------------


class TestBuildBuiltinImportCandidate:
    def test_missing_status_for_absent_skill(
        self,
        builtin_registry,
        monkeypatch,
    ):
        monkeypatch.setattr(
            reg,
            "get_builtin_skill_language_preference",
            lambda: "en",
        )
        candidate = reg._build_builtin_import_candidate(
            "browser",
            pool_skills={},
            registry=builtin_registry,
        )
        assert candidate["status"] == "missing"
        assert candidate["available_languages"] == ["en", "zh"]
        assert candidate["current_source"] == ""

    def test_current_status_for_installed_builtin(
        self,
        builtin_registry,
        monkeypatch,
    ):
        monkeypatch.setattr(
            reg,
            "get_builtin_skill_language_preference",
            lambda: "en",
        )
        monkeypatch.setattr(
            reg,
            "get_skill_pool_dir",
            lambda: Path("/nonexistent"),
        )
        pool_skills = {
            "browser": {
                "source": "builtin",
                "version_text": "2.0",
                "builtin_language": "en",
            },
        }
        candidate = reg._build_builtin_import_candidate(
            "browser",
            pool_skills=pool_skills,
            registry=builtin_registry,
        )
        assert candidate["status"] == "current"
        assert candidate["current_language"] == "en"

    def test_alias_name_canonicalised(self, builtin_registry, monkeypatch):
        monkeypatch.setattr(
            reg,
            "get_builtin_skill_language_preference",
            lambda: "en",
        )
        candidate = reg._build_builtin_import_candidate(
            "browser-en",
            pool_skills={},
            registry=builtin_registry,
        )
        assert candidate["name"] == "browser"

    def test_unknown_skill_empty_candidate(
        self,
        builtin_registry,
        monkeypatch,
    ):
        monkeypatch.setattr(
            reg,
            "get_builtin_skill_language_preference",
            lambda: "en",
        )
        candidate = reg._build_builtin_import_candidate(
            "ghost",
            pool_skills={},
            registry=builtin_registry,
        )
        assert candidate["status"] == "missing"
        assert candidate["available_languages"] == []


# ---------------------------------------------------------------------------
# _select_builtin_variant
# ---------------------------------------------------------------------------


class TestSelectBuiltinVariant:
    def test_selects_requested_language(self, builtin_registry):
        variant = reg._select_builtin_variant(
            builtin_registry,
            "browser",
            "zh",
        )
        assert variant is not None
        assert variant.language == "zh"

    def test_unknown_skill_returns_none(self, builtin_registry):
        assert reg._select_builtin_variant(builtin_registry, "ghost") is None

    def test_fallback_to_first_language(self, builtin_registry, monkeypatch):
        monkeypatch.setattr(
            reg,
            "get_builtin_skill_language_preference",
            lambda: "en",
        )
        variant = reg._select_builtin_variant(builtin_registry, "browser")
        assert variant is not None
        assert variant.language == "en"


# ---------------------------------------------------------------------------
# _normalize_builtin_import_requests
# ---------------------------------------------------------------------------


class TestNormalizeBuiltinImportRequests:
    def test_valid_request(self, builtin_registry):
        (
            normalized,
            unknown,
            unsupported,
        ) = reg._normalize_builtin_import_requests(
            [{"skill_name": "browser", "language": "zh"}],
            builtin_registry,
            {"browser": {}},
        )
        assert normalized == [("browser", "zh")]
        assert unknown == []
        assert unsupported == []

    def test_alias_with_language(self, builtin_registry):
        normalized, _, _ = reg._normalize_builtin_import_requests(
            [{"skill_name": "browser-zh"}],
            builtin_registry,
            {"browser": {}},
        )
        assert normalized == [("browser", "zh")]

    def test_unknown_skill_reported(self, builtin_registry):
        _, unknown, _ = reg._normalize_builtin_import_requests(
            [{"skill_name": "ghost"}],
            builtin_registry,
            {},
        )
        assert unknown == ["ghost"]

    def test_unsupported_language_falls_back_to_default(
        self,
        builtin_registry,
    ):
        # An unsupported requested language is normalised to the default
        # fallback (never reported as unsupported).
        (
            normalized,
            unknown,
            unsupported,
        ) = reg._normalize_builtin_import_requests(
            [{"skill_name": "solo", "language": "fr"}],
            builtin_registry,
            {"solo": {}},
            preferred_language="en",
        )
        assert normalized == [("solo", "en")]
        assert unknown == []
        assert unsupported == []

    def test_empty_name_reported(self, builtin_registry):
        _, unknown, _ = reg._normalize_builtin_import_requests(
            [{"skill_name": ""}],
            builtin_registry,
            {},
        )
        assert unknown == ["<empty>"]


# ---------------------------------------------------------------------------
# _collect_builtin_import_conflicts
# ---------------------------------------------------------------------------


class TestCollectBuiltinImportConflicts:
    def _candidate(self, **overrides):
        candidate = {
            "current_source": "builtin",
            "current_language": "en",
            "current_version_text": "1.0",
            "languages": {
                "zh": {
                    "status": "outdated",
                    "source_name": "browser-zh",
                    "version_text": "2.0",
                },
            },
        }
        candidate.update(overrides)
        return candidate

    def test_no_conflict_when_not_installed(self):
        conflicts = reg._collect_builtin_import_conflicts(
            [("browser", "zh")],
            {"browser": self._candidate(current_source="")},
        )
        assert conflicts == []

    def test_language_switch_conflict(self):
        conflicts = reg._collect_builtin_import_conflicts(
            [("browser", "zh")],
            {"browser": self._candidate()},
        )
        assert len(conflicts) == 1
        assert conflicts[0]["status"] == "language_switch"
        assert conflicts[0]["current_language"] == "en"

    def test_outdated_conflict_same_language(self):
        candidate = self._candidate(
            current_language="zh",
            languages={
                "zh": {
                    "status": "outdated",
                    "source_name": "browser-zh",
                    "version_text": "2.0",
                },
            },
        )
        conflicts = reg._collect_builtin_import_conflicts(
            [("browser", "zh")],
            {"browser": candidate},
        )
        assert len(conflicts) == 1
        assert conflicts[0]["status"] == "outdated"

    def test_current_status_no_conflict(self):
        candidate = self._candidate(
            current_language="zh",
            languages={
                "zh": {
                    "status": "current",
                    "source_name": "browser-zh",
                    "version_text": "2.0",
                },
            },
        )
        conflicts = reg._collect_builtin_import_conflicts(
            [("browser", "zh")],
            {"browser": candidate},
        )
        assert conflicts == []


# ---------------------------------------------------------------------------
# _canonical_builtin_skill_name / _parse_builtin_skill_identity
# ---------------------------------------------------------------------------


class TestCanonicalNames:
    def test_parse_identity(self):
        identity = reg._parse_builtin_skill_identity("browser-en")
        assert identity is not None
        assert identity.name == "browser"
        assert identity.language == "en"

    def test_parse_identity_invalid(self):
        assert reg._parse_builtin_skill_identity("") is None
        assert reg._parse_builtin_skill_identity("plain") is None

    def test_canonical_with_registry(self, builtin_registry):
        assert (
            reg._canonical_builtin_skill_name("browser-zh", builtin_registry)
            == "browser"
        )

    def test_canonical_not_in_registry_passthrough(self, builtin_registry):
        assert (
            reg._canonical_builtin_skill_name("other-zh", builtin_registry)
            == "other-zh"
        )

    def test_canonical_no_registry(self):
        assert reg._canonical_builtin_skill_name("browser-en") == "browser"


# ---------------------------------------------------------------------------
# _normalize_builtin_skill_language
# ---------------------------------------------------------------------------


class TestNormalizeBuiltinSkillLanguage:
    def test_known_language(self):
        assert reg._normalize_builtin_skill_language("zh") == "zh"
        assert reg._normalize_builtin_skill_language("EN") == "en"

    def test_unknown_falls_back(self):
        assert reg._normalize_builtin_skill_language("fr") == "en"
        assert reg._normalize_builtin_skill_language("", fallback="zh") == "zh"

    def test_invalid_fallback_defaults_en(self):
        assert reg._normalize_builtin_skill_language("", fallback="xx") == "en"

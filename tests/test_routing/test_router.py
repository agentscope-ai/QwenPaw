# -*- coding: utf-8 -*-
"""Tests for SkillRouter — bypass logic and fallback behavior."""

import pytest

from copaw.routing.config import SemanticRoutingConfig
from copaw.routing.router import SkillRouter


def _make_skills(n: int) -> list[dict]:
    """Generate n dummy skill metadata dicts."""
    return [
        {"name": f"skill-{i}", "description": f"Description for skill {i}"}
        for i in range(n)
    ]


class TestSkillRouterBypass:
    """Property 4: Small skill pool bypass."""

    def test_bypass_when_skills_lte_top_k(self):
        config = SemanticRoutingConfig(enabled=True, top_k=10)
        router = SkillRouter(config=config)
        skills = _make_skills(5)  # 5 <= 10

        result = router.route("some query", skills)

        assert result.bypassed is True
        assert len(result.hits) == 5
        assert result.total_skills == 5

    def test_bypass_when_skills_equal_top_k(self):
        config = SemanticRoutingConfig(enabled=True, top_k=3)
        router = SkillRouter(config=config)
        skills = _make_skills(3)  # 3 == 3

        result = router.route("query", skills)

        assert result.bypassed is True
        assert len(result.hits) == 3

    def test_bypass_empty_query(self):
        config = SemanticRoutingConfig(enabled=True, top_k=5)
        router = SkillRouter(config=config)
        skills = _make_skills(20)

        result = router.route("", skills)

        assert result.bypassed is True
        assert len(result.hits) == 20

    def test_bypass_whitespace_query(self):
        config = SemanticRoutingConfig(enabled=True, top_k=5)
        router = SkillRouter(config=config)
        skills = _make_skills(20)

        result = router.route("   ", skills)

        assert result.bypassed is True

    def test_bypass_empty_skills(self):
        config = SemanticRoutingConfig(enabled=True, top_k=10)
        router = SkillRouter(config=config)

        result = router.route("query", [])

        assert result.bypassed is True
        assert result.total_skills == 0
        assert result.hits == []


class TestSkillRouterFallback:
    """Test graceful fallback when deps are missing or model fails."""

    def test_fallback_on_large_pool_without_deps(self):
        """When skills > top_k but FAISS/ST not available, should fallback."""
        config = SemanticRoutingConfig(enabled=True, top_k=3)
        router = SkillRouter(config=config)
        skills = _make_skills(10)

        # This will try to use SemanticIndex which needs sentence-transformers.
        # If not installed, it should catch the error and return bypass.
        result = router.route("analyze data", skills)

        # Either it works (deps installed) or falls back (bypass=True)
        assert result is not None
        assert result.total_skills == 10
        if not result.bypassed:
            # If deps are available, should return <= top_k results
            assert len(result.hits) <= config.top_k

    def test_bypass_result_has_all_skill_names(self):
        config = SemanticRoutingConfig(enabled=True, top_k=10)
        router = SkillRouter(config=config)
        skills = _make_skills(5)

        result = router.route("query", skills)

        names = {h.item.name for h in result.hits}
        expected = {f"skill-{i}" for i in range(5)}
        assert names == expected

    def test_bypass_scores_are_1(self):
        """Bypass results should have score=1.0 for all hits."""
        config = SemanticRoutingConfig(enabled=True, top_k=10)
        router = SkillRouter(config=config)
        skills = _make_skills(3)

        result = router.route("query", skills)

        for hit in result.hits:
            assert hit.score == 1.0

    def test_skills_without_name_are_skipped(self):
        config = SemanticRoutingConfig(enabled=True, top_k=10)
        router = SkillRouter(config=config)
        skills = [
            {"name": "valid", "description": "A valid skill"},
            {"name": "", "description": "Empty name"},
            {"description": "No name key"},
        ]

        result = router.route("query", skills)

        names = [h.item.name for h in result.hits]
        assert names == ["valid"]

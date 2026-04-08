# -*- coding: utf-8 -*-
"""Tests for routing data models and serialization."""

import json
import pytest

from copaw.routing.models import IndexItem, SearchHit, RoutingResult


class TestIndexItem:
    def test_basic_creation(self):
        item = IndexItem(
            id="skill:web-scraper",
            name="web-scraper",
            description="Scrape web pages",
            source="skill_pool",
        )
        assert item.id == "skill:web-scraper"
        assert item.name == "web-scraper"
        assert item.source == "skill_pool"
        assert item.metadata == {}

    def test_with_metadata(self):
        item = IndexItem(
            id="mcp:fs:read_file",
            name="read_file",
            description="Read a file",
            source="mcp:filesystem",
            metadata={"server": "filesystem"},
        )
        assert item.metadata["server"] == "filesystem"


class TestRoutingResultSerialization:
    """Property 5: RoutingResult serialization round-trip."""

    def _make_result(self, **kwargs):
        defaults = {
            "hits": [
                SearchHit(
                    item=IndexItem(
                        id="skill:pdf",
                        name="pdf-converter",
                        description="Convert PDF files",
                        source="skill_pool",
                    ),
                    score=0.95,
                ),
                SearchHit(
                    item=IndexItem(
                        id="skill:csv",
                        name="csv-parser",
                        description="Parse CSV data",
                        source="skill_pool",
                    ),
                    score=0.82,
                ),
            ],
            "query": "convert document",
            "total_skills": 50,
            "bypassed": False,
        }
        defaults.update(kwargs)
        return RoutingResult(**defaults)

    def test_round_trip_basic(self):
        """Serialize then deserialize should produce equivalent result."""
        original = self._make_result()
        json_str = original.to_json()
        restored = RoutingResult.from_json(json_str)

        assert len(restored.hits) == len(original.hits)
        assert restored.query == original.query
        assert restored.total_skills == original.total_skills
        assert restored.bypassed == original.bypassed
        for orig_hit, rest_hit in zip(original.hits, restored.hits):
            assert rest_hit.item.id == orig_hit.item.id
            assert rest_hit.item.name == orig_hit.item.name
            assert rest_hit.item.description == orig_hit.item.description
            assert rest_hit.item.source == orig_hit.item.source
            assert rest_hit.score == orig_hit.score

    def test_round_trip_unicode(self):
        """Non-ASCII characters should be preserved (ensure_ascii=False)."""
        result = self._make_result(
            hits=[
                SearchHit(
                    item=IndexItem(
                        id="skill:翻译",
                        name="翻译工具",
                        description="将中文翻译为英文",
                        source="skill_pool",
                    ),
                    score=0.88,
                ),
            ],
            query="翻译这段话",
        )
        json_str = result.to_json()
        # Verify raw JSON contains Chinese characters (not escaped)
        assert "翻译工具" in json_str
        assert "将中文翻译为英文" in json_str

        restored = RoutingResult.from_json(json_str)
        assert restored.hits[0].item.name == "翻译工具"
        assert restored.hits[0].item.description == "将中文翻译为英文"
        assert restored.query == "翻译这段话"

    def test_round_trip_empty_hits(self):
        result = self._make_result(hits=[], total_skills=0, bypassed=True)
        restored = RoutingResult.from_json(result.to_json())
        assert restored.hits == []
        assert restored.bypassed is True

    def test_round_trip_edge_scores(self):
        """Scores at boundaries 0.0 and 1.0."""
        result = self._make_result(
            hits=[
                SearchHit(
                    item=IndexItem(
                        id="s:a", name="a", description="d", source="skill_pool"
                    ),
                    score=0.0,
                ),
                SearchHit(
                    item=IndexItem(
                        id="s:b", name="b", description="d", source="skill_pool"
                    ),
                    score=1.0,
                ),
            ],
        )
        restored = RoutingResult.from_json(result.to_json())
        assert restored.hits[0].score == 0.0
        assert restored.hits[1].score == 1.0

    def test_to_dict_structure(self):
        result = self._make_result()
        d = result.to_dict()
        assert "hits" in d
        assert "query" in d
        assert "total_skills" in d
        assert "bypassed" in d
        assert isinstance(d["hits"], list)
        assert "item" in d["hits"][0]
        assert "score" in d["hits"][0]

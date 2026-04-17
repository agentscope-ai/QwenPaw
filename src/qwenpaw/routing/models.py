# -*- coding: utf-8 -*-
"""Data models for semantic skill routing.

Pure Python dataclasses with no heavy dependencies — safe to import
regardless of whether sentence-transformers is installed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class IndexItem:
    """A single entry in the semantic index.

    Represents either a skill from the Skill Pool or an MCP tool.
    """

    id: str
    name: str
    description: str
    source: str  # "skill_pool" | "mcp:{server_name}"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchHit:
    """A single search result from the semantic index."""

    item: IndexItem
    score: float  # similarity score, 0.0 ~ 1.0


@dataclass
class RoutingResult:
    """Result of semantic skill routing."""

    hits: list[SearchHit]
    query: str
    total_skills: int
    bypassed: bool  # True when skill count <= top_k (no retrieval needed)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "hits": [
                {
                    "item": asdict(h.item),
                    "score": h.score,
                }
                for h in self.hits
            ],
            "query": self.query,
            "total_skills": self.total_skills,
            "bypassed": self.bypassed,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string (preserves non-ASCII characters)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RoutingResult:
        """Deserialize from a plain dict."""
        hits = [
            SearchHit(
                item=IndexItem(**h["item"]),
                score=h["score"],
            )
            for h in d["hits"]
        ]
        return cls(
            hits=hits,
            query=d["query"],
            total_skills=d["total_skills"],
            bypassed=d["bypassed"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> RoutingResult:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(json_str))

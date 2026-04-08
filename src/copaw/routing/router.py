# -*- coding: utf-8 -*-
"""Semantic skill router.

Filters a list of skills by semantic relevance to the user query.
Falls back gracefully when optional dependencies are missing or
when the embedding model fails to load.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import SemanticRoutingConfig
from .models import IndexItem, RoutingResult, SearchHit

logger = logging.getLogger(__name__)


class SkillRouter:
    """Semantic skill retrieval engine.

    Parameters
    ----------
    config:
        Routing configuration (top_k, encoder, etc.).
    persist_dir:
        Optional directory for FAISS index persistence.
    """

    def __init__(
        self,
        config: SemanticRoutingConfig,
        persist_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._persist_dir = persist_dir
        self._index: Any = None  # SemanticIndex (lazy)
        self._dirty = True  # True → index needs (re)build

    def route(
        self,
        query: str,
        skills: list[dict[str, Any]],
    ) -> RoutingResult:
        """Filter *skills* by semantic relevance to *query*.

        Each element in *skills* should be a dict with at least
        ``name`` and ``description`` keys (matching CoPaw's skill
        metadata format from ``_build_skill_metadata``).

        When ``len(skills) <= top_k`` the full list is returned
        without vector retrieval (bypass mode).

        On any failure the method returns a bypass result so that
        CoPaw's original behaviour is preserved.
        """
        top_k = self._config.top_k
        total = len(skills)

        # Bypass: small pool or empty query
        if total <= top_k or not query.strip():
            return self._bypass_result(query, skills)

        try:
            items = self._skills_to_items(skills)
            index = self._ensure_index(items)
            hits = index.search(query, top_k=top_k)
            return RoutingResult(
                hits=hits,
                query=query,
                total_skills=total,
                bypassed=False,
            )
        except Exception as exc:
            logger.warning(
                "Semantic routing failed, falling back to full skill list: %s",
                exc,
            )
            return self._bypass_result(query, skills)

    def invalidate(self) -> None:
        """Mark the index as stale so it is rebuilt on next query."""
        self._dirty = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_index(self, items: list[IndexItem]) -> Any:
        """Return a ready SemanticIndex, rebuilding if necessary."""
        from .index import SemanticIndex

        if self._index is None:
            self._index = SemanticIndex(
                encoder_name=self._config.encoder,
                persist_dir=self._persist_dir,
            )
            # Try loading persisted index first
            if self._index.load():
                if not self._index.needs_rebuild(items):
                    self._dirty = False
                    return self._index

        if self._dirty or self._index.needs_rebuild(items):
            self._index.build(items)
            self._index.save()
            self._dirty = False

        return self._index

    @staticmethod
    def _skills_to_items(skills: list[dict[str, Any]]) -> list[IndexItem]:
        """Convert CoPaw skill metadata dicts to IndexItems."""
        items: list[IndexItem] = []
        for sk in skills:
            name = sk.get("name", "")
            desc = sk.get("description", "")
            if not name:
                continue
            items.append(
                IndexItem(
                    id=f"skill:{name}",
                    name=name,
                    description=desc,
                    source="skill_pool",
                )
            )
        return items

    @staticmethod
    def _bypass_result(
        query: str,
        skills: list[dict[str, Any]],
    ) -> RoutingResult:
        """Build a RoutingResult that includes all skills (no filtering)."""
        hits = [
            SearchHit(
                item=IndexItem(
                    id=f"skill:{sk.get('name', '')}",
                    name=sk.get("name", ""),
                    description=sk.get("description", ""),
                    source="skill_pool",
                ),
                score=1.0,
            )
            for sk in skills
            if sk.get("name")
        ]
        return RoutingResult(
            hits=hits,
            query=query,
            total_skills=len(skills),
            bypassed=True,
        )

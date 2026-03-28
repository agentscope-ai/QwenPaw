# -*- coding: utf-8 -*-
"""Unit tests for knowledge search service."""

from __future__ import annotations

import json
from pathlib import Path

from copaw.agents.knowledge.search_service import KnowledgeSearchService


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _seed_knowledge_workspace(workspace_dir: Path) -> None:
    index = {
        "version": 1,
        "updated_at": "2026-03-28T00:00:00Z",
        "documents": {
            "einstein-doc": {
                "doc_id": "einstein-doc",
                "title": "Einstein Facts",
                "source_file": "einstein.md",
                "source_type": "md",
                "imported_at": "2026-03-28T10:00:00Z",
                "paths": {
                    "chunks": "knowledge/chunks/einstein-doc.json",
                },
            },
            "ml-doc": {
                "doc_id": "ml-doc",
                "title": "ML Notes",
                "source_file": "ml.txt",
                "source_type": "txt",
                "imported_at": "2026-03-28T09:00:00Z",
                "paths": {
                    "chunks": "knowledge/chunks/ml-doc.json",
                },
            },
        },
        "source_hash_to_doc_id": {},
        "content_hash_to_doc_id": {},
    }
    _write_json(workspace_dir / "knowledge/state/index.json", index)

    _write_json(
        workspace_dir / "knowledge/chunks/einstein-doc.json",
        {
            "doc_id": "einstein-doc",
            "chunk_count": 2,
            "chunks": [
                {
                    "chunk_id": "chunk-0000",
                    "index": 0,
                    "text": "Albert Einstein was born in 1879 in Ulm.",
                    "char_count": 41,
                },
                {
                    "chunk_id": "chunk-0001",
                    "index": 1,
                    "text": "He published papers on relativity.",
                    "char_count": 35,
                },
            ],
        },
    )
    _write_json(
        workspace_dir / "knowledge/chunks/ml-doc.json",
        {
            "doc_id": "ml-doc",
            "chunk_count": 1,
            "chunks": [
                {
                    "chunk_id": "chunk-0000",
                    "index": 0,
                    "text": "Machine learning includes supervised learning.",
                    "char_count": 47,
                },
            ],
        },
    )


def test_search_returns_relevant_hit(tmp_path: Path) -> None:
    _seed_knowledge_workspace(tmp_path)
    service = KnowledgeSearchService(tmp_path)

    hits = service.search("Einstein 1879", max_results=3, min_score=0.2)

    assert hits
    assert hits[0].doc_id == "einstein-doc"
    assert "einstein" in hits[0].chunk_text.lower()


def test_search_respects_min_score(tmp_path: Path) -> None:
    _seed_knowledge_workspace(tmp_path)
    service = KnowledgeSearchService(tmp_path)

    hits = service.search(
        "totally unrelated topic",
        max_results=3,
        min_score=0.4,
    )

    assert not hits


def test_listing_query_returns_preview_when_no_keyword_match(
    tmp_path: Path,
) -> None:
    _seed_knowledge_workspace(tmp_path)
    service = KnowledgeSearchService(tmp_path)

    hits = service.search("知识库有什么知识", max_results=2, min_score=0.1)

    assert len(hits) == 2
    assert {hit.doc_id for hit in hits} == {"einstein-doc", "ml-doc"}
    assert all(hit.score >= 0.2 for hit in hits)

# -*- coding: utf-8 -*-
"""Unit tests for knowledge repository helpers."""

from __future__ import annotations

from pathlib import Path

from copaw.agents.knowledge.repository import KnowledgeRepository


def test_load_index_returns_default_for_invalid_json(tmp_path: Path) -> None:
    repo = KnowledgeRepository(tmp_path)
    repo.ensure_dirs()
    repo.index_path.write_text("{invalid-json", encoding="utf-8")

    index = repo.load_index()

    assert index["version"] == 1
    assert index["documents"] == {}
    assert index["source_hash_to_doc_id"] == {}
    assert index["content_hash_to_doc_id"] == {}

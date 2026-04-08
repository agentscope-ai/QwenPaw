# -*- coding: utf-8 -*-
"""Tests for knowledge_search tool wrapper."""

from __future__ import annotations

import json
from pathlib import Path

from copaw.agents.tools.knowledge_search import create_knowledge_search_tool


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _seed_workspace(workspace_dir: Path) -> None:
    _write_json(
        workspace_dir / "knowledge/state/index.json",
        {
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
            },
            "source_hash_to_doc_id": {},
            "content_hash_to_doc_id": {},
        },
    )
    _write_json(
        workspace_dir / "knowledge/chunks/einstein-doc.json",
        {
            "doc_id": "einstein-doc",
            "chunk_count": 1,
            "chunks": [
                {
                    "chunk_id": "chunk-0000",
                    "index": 0,
                    "text": "Albert Einstein was born in 1879 in Ulm.",
                    "char_count": 41,
                },
            ],
        },
    )


async def test_knowledge_search_tool_returns_hits(tmp_path: Path) -> None:
    _seed_workspace(tmp_path)
    tool = create_knowledge_search_tool(tmp_path)

    response = await tool("Einstein 1879")

    assert response.content
    text = response.content[0]["text"]
    assert "Found 1 knowledge hit(s)" in text
    assert "einstein-doc" in text
    assert "Albert Einstein" in text


async def test_knowledge_search_tool_empty_query() -> None:
    tool = create_knowledge_search_tool("/tmp/non-exist")

    response = await tool("   ")

    assert "query must not be empty" in response.content[0]["text"]

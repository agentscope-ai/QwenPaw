# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace
import importlib

from copaw.agents.tools.knowledge_search import knowledge_search


async def test_knowledge_search_rejects_empty_query() -> None:
    result = await knowledge_search("   ")
    text = result.content[0]["text"]
    assert "query cannot be empty" in text


async def test_knowledge_search_returns_disabled_message(monkeypatch) -> None:
    module = importlib.import_module("copaw.agents.tools.knowledge_search")

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(enabled=False),
            agents=SimpleNamespace(
                running=SimpleNamespace(knowledge_retrieval_enabled=True),
            ),
        ),
    )

    result = await module.knowledge_search("how to index docs")
    text = result.content[0]["text"]
    assert "Knowledge is disabled" in text


async def test_knowledge_search_returns_runtime_disabled_message(
    monkeypatch,
) -> None:
    module = importlib.import_module("copaw.agents.tools.knowledge_search")

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(enabled=True),
            agents=SimpleNamespace(
                running=SimpleNamespace(knowledge_retrieval_enabled=False),
            ),
        ),
    )

    result = await module.knowledge_search("how to index docs")
    text = result.content[0]["text"]
    assert "Knowledge retrieval is disabled" in text


async def test_knowledge_search_formats_hits(monkeypatch) -> None:
    module = importlib.import_module("copaw.agents.tools.knowledge_search")

    class _FakeManager:
        def __init__(self, working_dir) -> None:
            _ = working_dir

        def search(
            self,
            query: str,
            config,
            limit: int = 10,
            source_ids=None,
            source_types=None,
        ):
            _ = config, source_ids
            assert query == "knowledge index"
            assert limit == 2
            assert source_types == ["file"]
            return {
                "query": query,
                "hits": [
                    {
                        "source_name": "Project Docs",
                        "source_type": "file",
                        "document_title": "Index Guide",
                        "document_path": "docs/index.md",
                        "score": 2.5,
                        "snippet": "Run index after adding sources.",
                    },
                    {
                        "source_name": "Low Score",
                        "source_type": "file",
                        "document_title": "Ignore",
                        "document_path": "docs/low.md",
                        "score": 0.2,
                        "snippet": "too low",
                    },
                ],
            }

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(enabled=True),
            agents=SimpleNamespace(
                running=SimpleNamespace(knowledge_retrieval_enabled=True),
            ),
        ),
    )
    monkeypatch.setattr(module, "KnowledgeManager", _FakeManager)

    result = await module.knowledge_search(
        query="knowledge index",
        max_results=2,
        min_score=1.0,
        source_types=["file"],
    )
    text = result.content[0]["text"]
    assert "Knowledge search results for: knowledge index" in text
    assert "[1] Project Docs (file) score=2.50" in text
    assert "title: Index Guide" in text
    assert "path: docs/index.md" in text
    assert "snippet: Run index after adding sources." in text
    assert "Low Score" not in text

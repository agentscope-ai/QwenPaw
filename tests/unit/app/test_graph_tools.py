# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

from copaw.config.config import Config, KnowledgeSourceSpec
from copaw.knowledge.manager import KnowledgeManager


async def test_graph_query_requires_graph_enabled(monkeypatch) -> None:
    module = importlib.import_module("copaw.agents.tools.graph_query")

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(enabled=True, graph_query_enabled=False),
        ),
    )

    result = await module.graph_query("find relation")
    text = result.content[0]["text"]
    assert "graph query is disabled" in text


async def test_graph_query_formats_payload(monkeypatch) -> None:
    module = importlib.import_module("copaw.agents.tools.graph_query")

    class _FakeGraphOpsManager:
        def __init__(self, working_dir) -> None:
            _ = working_dir

        def graph_query(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(
                records=[{"subject": "A", "predicate": "rel", "object": "B"}],
                summary="ok",
                provenance={"engine": "local_lexical"},
                warnings=[],
            )

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                enabled=True,
                graph_query_enabled=True,
                allow_cypher_query=False,
            ),
        ),
    )
    monkeypatch.setattr(module, "GraphOpsManager", _FakeGraphOpsManager)

    result = await module.graph_query("find relation", query_mode="template")
    payload = json.loads(result.content[0]["text"])
    assert payload["summary"] == "ok"
    assert payload["records"][0]["subject"] == "A"


async def test_memify_run_requires_memify_enabled(monkeypatch) -> None:
    module = importlib.import_module("copaw.agents.tools.memify_run")

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(enabled=True, memify_enabled=False),
        ),
    )
    result = await module.memify_run()
    text = result.content[0]["text"]
    assert "memify is disabled" in text


async def test_memify_run_returns_job_payload(monkeypatch) -> None:
    module = importlib.import_module("copaw.agents.tools.memify_run")

    class _FakeGraphOpsManager:
        def __init__(self, working_dir) -> None:
            _ = working_dir

        def run_memify(self, **kwargs):
            _ = kwargs
            return {
                "accepted": True,
                "job_id": "job123",
                "estimated_steps": 1,
                "status_url": "/knowledge/memify/jobs/job123",
            }

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(enabled=True, memify_enabled=True),
        ),
    )
    monkeypatch.setattr(module, "GraphOpsManager", _FakeGraphOpsManager)

    result = await module.memify_run(pipeline_type="default")
    payload = json.loads(result.content[0]["text"])
    assert payload["accepted"] is True
    assert payload["job_id"] == "job123"


async def test_memify_status_handles_not_found(monkeypatch) -> None:
    module = importlib.import_module("copaw.agents.tools.memify_status")

    class _FakeGraphOpsManager:
        def __init__(self, working_dir) -> None:
            _ = working_dir

        def get_memify_status(self, job_id: str):
            _ = job_id
            return None

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(enabled=True, memify_enabled=True),
        ),
    )
    monkeypatch.setattr(module, "GraphOpsManager", _FakeGraphOpsManager)

    result = await module.memify_status("missing-job")
    text = result.content[0]["text"]
    assert "memify job not found" in text


async def test_triplet_focus_search_requires_enabled(monkeypatch) -> None:
    module = importlib.import_module("copaw.agents.tools.triplet_focus_search")

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(enabled=True, triplet_search_enabled=False),
        ),
    )

    result = await module.triplet_focus_search(query_text="entity relation")
    text = result.content[0]["text"]
    assert "triplet-focused search is disabled" in text


async def test_triplet_focus_search_formats_payload(monkeypatch) -> None:
    module = importlib.import_module("copaw.agents.tools.triplet_focus_search")

    class _FakeGraphOpsManager:
        def __init__(self, working_dir) -> None:
            _ = working_dir

        def graph_query(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(
                records=[
                    {
                        "subject": "Agent",
                        "predicate": "uses",
                        "object": "Tool",
                        "score": 2.0,
                        "source_id": "s1",
                        "source_type": "text",
                        "document_path": "docs/a.md",
                        "document_title": "A",
                    }
                ],
                warnings=[],
            )

    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(enabled=True, triplet_search_enabled=True),
        ),
    )
    monkeypatch.setattr(module, "GraphOpsManager", _FakeGraphOpsManager)

    result = await module.triplet_focus_search(query_text="Agent uses Tool")
    payload = json.loads(result.content[0]["text"])
    assert payload["triplets"][0]["subject"] == "Agent"
    assert payload["triplets"][0]["predicate"] == "uses"
    assert payload["triplets"][0]["object"] == "Tool"


async def test_graph_tool_chain_smoke_local_engine(
    monkeypatch,
    tmp_path,
) -> None:
    graph_query_module = importlib.import_module("copaw.agents.tools.graph_query")
    memify_run_module = importlib.import_module("copaw.agents.tools.memify_run")
    memify_status_module = importlib.import_module("copaw.agents.tools.memify_status")
    triplet_module = importlib.import_module("copaw.agents.tools.triplet_focus_search")

    knowledge_config = Config().knowledge
    knowledge_config.enabled = True
    knowledge_config.graph_query_enabled = True
    knowledge_config.triplet_search_enabled = True
    knowledge_config.memify_enabled = True

    manager = KnowledgeManager(tmp_path)
    source = KnowledgeSourceSpec(
        id="smoke-text-source",
        name="Smoke Source",
        type="text",
        content="Agent uses tool for graph data processing.",
        enabled=True,
        recursive=False,
        tags=["smoke"],
        summary="",
    )
    knowledge_config.sources.append(source)
    manager.index_source(
        source,
        knowledge_config,
        SimpleNamespace(knowledge_chunk_size=knowledge_config.index.chunk_size),
    )

    load_config_stub = lambda: SimpleNamespace(knowledge=knowledge_config)
    for module in [
        graph_query_module,
        memify_run_module,
        memify_status_module,
        triplet_module,
    ]:
        monkeypatch.setattr(module, "load_config", load_config_stub)
        monkeypatch.setattr(module, "WORKING_DIR", tmp_path)

    memify_result = await memify_run_module.memify_run(
        pipeline_type="default",
        idempotency_key="graph-tool-chain-smoke",
    )
    memify_payload = json.loads(memify_result.content[0]["text"])
    assert memify_payload["accepted"] is True

    status_result = await memify_status_module.memify_status(memify_payload["job_id"])
    status_payload = json.loads(status_result.content[0]["text"])
    assert status_payload["job_id"] == memify_payload["job_id"]
    assert status_payload["status"] == "succeeded"

    graph_result = await graph_query_module.graph_query(
        query_text="Agent uses tool",
        query_mode="template",
    )
    graph_payload = json.loads(graph_result.content[0]["text"])
    assert len(graph_payload["records"]) >= 1

    triplet_result = await triplet_module.triplet_focus_search(
        query_text="Agent uses tool",
    )
    triplet_payload = json.loads(triplet_result.content[0]["text"])
    assert isinstance(triplet_payload["triplets"], list)
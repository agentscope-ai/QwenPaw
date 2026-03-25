#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick smoke test for Cognee capability paths in CoPaw.

Covers:
- Knowledge indexing via Cognee backend
- Knowledge search
- Graph query (template mode)
- Triplet-focused graph query
- Memify job trigger + status (dry-run by default)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from copaw.config.config import Config, KnowledgeSourceSpec
from copaw.knowledge.graph_ops import GraphOpsManager
from copaw.knowledge.manager import KnowledgeManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Cognee capability smoke test in local workspace.",
    )
    parser.add_argument(
        "--working-dir",
        default=str(REPO_ROOT / ".smoke-cognee-working"),
        help="Working directory for temporary knowledge artifacts.",
    )
    parser.add_argument(
        "--dataset-prefix",
        default="smoke-cognee",
        help="Cognee dataset prefix.",
    )
    parser.add_argument(
        "--query",
        default="Agent uses tool",
        help="Query string used for retrieval and graph tests.",
    )
    parser.add_argument(
        "--llm-model",
        default="",
        help=(
            "Explicit Cognee LLM model, usually with provider prefix, "
            "e.g. ollama/qwen3:8b or lm_studio/qwen2.5-7b-instruct."
        ),
    )
    parser.add_argument(
        "--llm-base-url",
        default="",
        help="Explicit Cognee LLM base URL, e.g. http://127.0.0.1:11434/v1.",
    )
    parser.add_argument(
        "--llm-api-key",
        default="",
        help="Explicit Cognee LLM API key. For local providers you can use 'local'.",
    )
    parser.add_argument(
        "--real-memify",
        action="store_true",
        help="Run real memify instead of dry-run.",
    )
    return parser.parse_args()


def build_knowledge_config(args: argparse.Namespace):
    config = Config().knowledge
    config.enabled = True
    config.graph_query_enabled = True
    config.triplet_search_enabled = True
    config.memify_enabled = True
    config.allow_cypher_query = False

    config.engine.provider = "cognee"
    config.engine.fallback_to_default = True

    config.cognee.enabled = True
    config.cognee.dataset_prefix = args.dataset_prefix
    config.cognee.search_mode = "hybrid"
    config.cognee.sync_with_copaw_provider = False

    if args.llm_model:
        config.cognee.llm_model = args.llm_model
    if args.llm_base_url:
        config.cognee.llm_base_url = args.llm_base_url
    if args.llm_api_key:
        config.cognee.llm_api_key = args.llm_api_key

    return config


def main() -> int:
    args = parse_args()
    working_dir = Path(args.working_dir).resolve()
    working_dir.mkdir(parents=True, exist_ok=True)

    knowledge_config = build_knowledge_config(args)

    source = KnowledgeSourceSpec(
        id="smoke-note",
        name="Smoke Note",
        type="text",
        content="Agent uses tool for graph data processing and memory enrichment.",
        enabled=True,
        recursive=False,
        tags=["smoke", "cognee"],
        description="Cognee smoke test source",
    )
    knowledge_config.sources = [source]

    manager = KnowledgeManager(working_dir)
    graph_manager = GraphOpsManager(working_dir)

    print("[1/5] Indexing source via KnowledgeManager...")
    indexed = manager.index_source(
        source,
        knowledge_config,
        SimpleNamespace(knowledge_chunk_size=knowledge_config.index.chunk_size),
    )
    print(json.dumps(indexed, ensure_ascii=False, indent=2))

    print("[2/5] Running retrieval search...")
    search_result = manager.search(
        query=args.query,
        config=knowledge_config,
        limit=5,
    )
    print(json.dumps(search_result, ensure_ascii=False, indent=2))
    if not search_result.get("hits"):
        print("ERROR: search returned no hits")
        return 2

    print("[3/5] Running graph_query(template)...")
    graph_result = graph_manager.graph_query(
        query_text=args.query,
        config=knowledge_config,
        query_mode="template",
        dataset_scope=None,
        top_k=5,
    )
    print(json.dumps(graph_result.__dict__, ensure_ascii=False, indent=2))
    if not graph_result.records:
        print("ERROR: graph_query returned no records")
        return 3

    print("[4/5] Running triplet-focused graph query...")
    triplet_result = graph_manager.graph_query(
        query_text=args.query,
        config=knowledge_config,
        query_mode="template",
        dataset_scope=None,
        top_k=10,
    )
    triplets = [
        {
            "subject": item.get("subject", ""),
            "predicate": item.get("predicate", ""),
            "object": item.get("object", ""),
            "score": item.get("score", 0),
        }
        for item in triplet_result.records
    ]
    print(json.dumps({"triplets": triplets[:5]}, ensure_ascii=False, indent=2))

    print("[5/5] Triggering memify job...")
    memify_run = graph_manager.run_memify(
        config=knowledge_config,
        pipeline_type="default",
        dataset_scope=None,
        dry_run=not args.real_memify,
        idempotency_key="smoke-cognee-capability",
    )
    print(json.dumps(memify_run, ensure_ascii=False, indent=2))

    job_id = memify_run.get("job_id")
    if not job_id:
        print("ERROR: memify did not return job_id")
        return 4

    status = graph_manager.get_memify_status(job_id)
    print("Memify status:")
    print(json.dumps(status, ensure_ascii=False, indent=2))

    if not isinstance(status, dict) or status.get("status") not in {
        "succeeded",
        "running",
        "accepted",
    }:
        print("ERROR: memify status is unexpected")
        return 5

    print("SUCCESS: Cognee capability smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

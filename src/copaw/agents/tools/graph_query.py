# -*- coding: utf-8 -*-
"""Tool to execute graph-oriented knowledge queries."""

from __future__ import annotations

import json

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config import load_config
from ...constant import WORKING_DIR
from ...knowledge.graph_ops import GraphOpsManager


async def graph_query(
    query_text: str,
    query_mode: str = "template",
    dataset_scope: list[str] | None = None,
    top_k: int = 10,
    timeout_sec: int = 20,
) -> ToolResponse:
    """Run graph-style query and return normalized records.

    Args:
        query_text: Text query or cypher query body.
        query_mode: One of "template" or "cypher".
        dataset_scope: Optional dataset names/ids for scoping.
        top_k: Maximum number of records to return.
        timeout_sec: Query timeout for backend provider.
    """
    text = (query_text or "").strip()
    if not text:
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: query_text cannot be empty.")],
        )

    mode = (query_mode or "template").strip().lower()
    if mode not in {"template", "cypher"}:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: query_mode must be 'template' or 'cypher'.",
                )
            ],
        )

    config = load_config()
    if not getattr(config, "knowledge", None) or not config.knowledge.enabled:
        return ToolResponse(
            content=[
                TextBlock(type="text", text="Error: knowledge is disabled in configuration."),
            ],
        )
    if not bool(getattr(config.knowledge, "graph_query_enabled", False)):
        return ToolResponse(
            content=[
                TextBlock(type="text", text="Error: graph query is disabled in configuration."),
            ],
        )
    if mode == "cypher" and not bool(getattr(config.knowledge, "allow_cypher_query", False)):
        return ToolResponse(
            content=[
                TextBlock(type="text", text="Error: cypher query is not allowed by configuration."),
            ],
        )

    try:
        manager = GraphOpsManager(WORKING_DIR)
        result = manager.graph_query(
            config=config.knowledge,
            query_mode=mode,
            query_text=text,
            dataset_scope=dataset_scope,
            top_k=max(1, min(int(top_k), 50)),
            timeout_sec=max(1, min(int(timeout_sec), 120)),
        )
        payload = {
            "records": result.records,
            "summary": result.summary,
            "provenance": result.provenance,
            "warnings": result.warnings,
        }
        return ToolResponse(
            content=[TextBlock(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))],
        )
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: graph query failed due to\n{e}")],
        )
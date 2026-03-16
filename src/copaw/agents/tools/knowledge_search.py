# -*- coding: utf-8 -*-
"""Tool to search indexed knowledge chunks."""

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config import load_config
from ...constant import WORKING_DIR
from ...knowledge import KnowledgeManager


async def knowledge_search(
    query: str,
    max_results: int = 5,
    min_score: float = 1.0,
    source_types: list[str] | None = None,
) -> ToolResponse:
    """Search knowledge sources and return the top matched snippets.

    Use this tool when you need project-specific facts from indexed
    knowledge sources instead of guessing from memory.

    Args:
        query: Search query text.
        max_results: Maximum number of hits to return.
        min_score: Minimum lexical score required for a hit.
        source_types: Optional source type filter, e.g. ["file", "url"].

    Returns:
        ToolResponse with formatted hit summaries.
    """
    query_text = (query or "").strip()
    if not query_text:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: query cannot be empty.",
                ),
            ],
        )

    try:
        config = load_config()
        if not getattr(config, "knowledge", None) or not config.knowledge.enabled:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="Knowledge is disabled in configuration.",
                    ),
                ],
            )
        if not bool(
            getattr(
                getattr(config, "agents", None),
                "running",
                None,
            )
            and getattr(config.agents.running, "knowledge_retrieval_enabled", True)
        ):
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="Knowledge retrieval is disabled in agent runtime configuration.",
                    ),
                ],
            )

        limit = max(1, min(int(max_results), 20))
        threshold = float(min_score)
        manager = KnowledgeManager(WORKING_DIR)
        result = manager.search(
            query=query_text,
            config=config.knowledge,
            limit=limit,
            source_types=source_types,
        )
        hits = [
            hit
            for hit in (result.get("hits") or [])
            if float(hit.get("score", 0) or 0) >= threshold
        ]

        if not hits:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="No relevant knowledge found.",
                    ),
                ],
            )

        lines: list[str] = [f"Knowledge search results for: {query_text}", ""]
        for index, hit in enumerate(hits, start=1):
            source_name = hit.get("source_name") or "unknown"
            source_type = hit.get("source_type") or "unknown"
            score = float(hit.get("score", 0) or 0)
            title = hit.get("document_title") or "(untitled)"
            path = hit.get("document_path") or ""
            snippet = (hit.get("snippet") or "").strip()

            lines.append(
                f"[{index}] {source_name} ({source_type}) score={score:.2f}",
            )
            lines.append(f"title: {title}")
            if path:
                lines.append(f"path: {path}")
            if snippet:
                lines.append(f"snippet: {snippet}")
            lines.append("")

        return ToolResponse(
            content=[TextBlock(type="text", text="\n".join(lines).strip())],
        )
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: knowledge search failed due to\n{e}",
                ),
            ],
        )

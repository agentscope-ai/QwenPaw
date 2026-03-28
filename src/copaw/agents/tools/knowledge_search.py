# -*- coding: utf-8 -*-
"""Knowledge search tool for imported knowledge documents."""

from __future__ import annotations

from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ..knowledge.search_service import KnowledgeSearchService


def create_knowledge_search_tool(workspace_dir: str | Path | None):
    """Create knowledge_search tool bound to one workspace directory."""
    resolved_workspace = (
        Path(workspace_dir).expanduser() if workspace_dir is not None else None
    )

    async def knowledge_search(
        query: str,
        max_results: int = 5,
        min_score: float = 0.12,
    ) -> ToolResponse:
        """
        Search imported knowledge chunks in this workspace.

        Use for questions like:
        - "What is in my knowledge base?"
        - "Do we have documents about X?"
        - "Find relevant notes from imported files about Y."
        """
        if resolved_workspace is None:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: Workspace is unavailable for "
                            "knowledge search."
                        ),
                    ),
                ],
            )

        normalized_query = (query or "").strip()
        if not normalized_query:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="Error: query must not be empty.",
                    ),
                ],
            )

        try:
            service = KnowledgeSearchService(resolved_workspace)
            hits = service.search(
                normalized_query,
                max_results=max_results,
                min_score=min_score,
            )
        except Exception as exc:  # pragma: no cover - guard rail
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: Knowledge search failed due to\n{exc}",
                    ),
                ],
            )

        if not hits:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "No matching knowledge found in imported "
                            "documents "
                            f"for query: {normalized_query}"
                        ),
                    ),
                ],
            )

        lines = [
            (
                f"Found {len(hits)} knowledge hit(s) for query: "
                f"{normalized_query}"
            ),
        ]
        for idx, hit in enumerate(hits, start=1):
            lines.extend(
                [
                    (
                        f"{idx}. [{hit.score:.3f}] {hit.title} "
                        f"({hit.source_file})"
                    ),
                    (
                        f"   doc_id: {hit.doc_id}, chunk: {hit.chunk_id}, "
                        f"source_type: {hit.source_type}"
                    ),
                    f"   snippet: {hit.chunk_text}",
                ],
            )

        return ToolResponse(
            content=[TextBlock(type="text", text="\n".join(lines))],
        )

    return knowledge_search


__all__ = ["create_knowledge_search_tool"]

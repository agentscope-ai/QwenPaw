# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Render source-backed grounding data for downstream Creator agents."""

from __future__ import annotations

from typing import Any


def _clean(value: Any, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_chars]


def fact_from_source(
    source: dict[str, Any],
    index: int,
) -> dict[str, Any] | None:
    title = _clean(source.get("title"), max_chars=140)
    snippet = _clean(source.get("snippet"), max_chars=360)
    if not title and not snippet:
        return None
    claim = f"{title}: {snippet}" if title and snippet else title or snippet
    return {"claim": claim, "source_indices": [index]}


def render_grounded_context(
    queries: list[str],
    facts: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    visual_sources: list[dict[str, Any]] | None = None,
) -> str:
    lines = ["Web grounding context", "", "Queries:"]
    lines.extend(f"- {query}" for query in queries)
    lines.extend(["", "Facts:"])
    if facts:
        lines.extend(
            f"- [{fact['source_indices'][0]}] {fact['claim']}"
            for fact in facts
        )
    else:
        lines.append("- No source-backed facts were found.")
    lines.extend(["", "Sources:"])
    if sources:
        lines.extend(
            f"[{source['index']}] {source.get('title', '')} - {source.get('url', '')}"
            for source in sources
        )
    else:
        lines.append("(none)")
    if visual_sources is not None:
        lines.extend(["", "Visual References:"])
        if visual_sources:
            for source in visual_sources:
                verification = source.get("verification")
                if not isinstance(verification, dict):
                    verification = {}
                status = verification.get("status") or "unverified"
                usage = verification.get("usage") or "context"
                score = verification.get("fit_score")
                score_text = f", score={score}" if score is not None else ""
                source_url = source.get("source_url") or ""
                source_text = f" source={source_url}" if source_url else ""
                local_url = (
                    source.get("local_url")
                    or source.get("vlm_image_url")
                    or ""
                )
                local_text = f" local={local_url}" if local_url else ""
                title = source.get("title") or "untitled visual reference"
                lines.append(
                    f"[V{source.get('rank') or source.get('index')}] "
                    f"{status}/{usage}{score_text}: {title} - "
                    f"{source.get('url', '')}{source_text}{local_text}",
                )
        else:
            lines.append("(none)")
    return "\n".join(lines)

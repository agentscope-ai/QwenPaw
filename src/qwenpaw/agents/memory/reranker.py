# -*- coding: utf-8 -*-
"""Provider-agnostic reranker for memory search results.

Exposes two functions:

* ``build_search_answer`` — format ranked candidates into a ReMe-style
  answer string with score metadata.
* ``rerank`` — call a standard ``/rerank`` endpoint (any provider),
  re-order candidates by ``relevance_score``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def build_search_answer(candidates: list[dict]) -> str:
    """Format re-ranked candidates as a ReMe-style search answer."""
    lines: list[str] = []
    for c in candidates:
        scores: dict[str, float] = c.get("scores", {})
        parts = [f"score={scores.get('score', 0.0):.4f}"]
        for key in ("vector", "keyword", "rerank"):
            val = scores.get(key)
            parts.append(f"{key}={val:.4f}" if val is not None else f"{key}=-")
        header = (
            f"========== {c['path']}:{c['start_line']}-{c['end_line']}"
            f" [{' '.join(parts)}] =========="
        )
        lines.append(header)
        lines.append(c["text"])
    return "\n".join(lines)


# pylint: disable=too-many-return-statements
async def rerank(
    query: str,
    candidates: list[dict],
    *,
    api_key: str,
    base_url: str,
    model_name: str,
    top_n: int | None = None,
) -> list[dict]:
    """Re-rank *candidates* via ``POST <base_url>``.

    The *base_url* is the **full** rerank endpoint URL, e.g.:
    - ``https://dashscope.aliyuncs.com/compatible-api/v1/reranks``
    - ``https://api.siliconflow.cn/v1/rerank``

    On any failure the original *candidates* are returned.
    """
    if not candidates:
        return candidates
    if not api_key:
        logger.warning("[rerank] api_key not configured")
        return candidates[:top_n] if top_n else candidates
    if not base_url:
        logger.warning("[rerank] base_url not configured")
        return candidates[:top_n] if top_n else candidates
    if not query:
        return candidates[:top_n] if top_n else candidates

    texts = [c.get("text", "") for c in candidates]

    payload: dict[str, Any] = {
        "model": model_name,
        "query": query,
        "documents": texts,
    }
    if top_n is not None:
        payload["top_n"] = top_n

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("[rerank] request failed")
        return candidates[:top_n] if top_n else candidates

    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        logger.warning("[rerank] empty results")
        return candidates[:top_n] if top_n else candidates

    reranked: list[dict] = []
    for item in results:
        idx = item.get("index")
        score = item.get("relevance_score")
        if idx is None or idx >= len(candidates):
            continue
        c = dict(candidates[idx])
        c["scores"] = {
            **(c.get("scores") or {}),
            "rerank": float(score) if score is not None else 0.0,
        }
        reranked.append(c)

    if not reranked:
        return candidates[:top_n] if top_n else candidates

    logger.info("[rerank] reordered %d results", len(reranked))
    return reranked

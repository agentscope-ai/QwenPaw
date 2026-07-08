# -*- coding: utf-8 -*-
"""Provider-agnostic reranker helper for memory search results.

Exposes two functions:

* ``build_search_answer`` — format ranked candidates into a ReMe-style
  answer string with score metadata.
* ``rerank`` — call a rerank API endpoint, re-order candidates by
  ``relevance_score``, and attach a ``rerank`` key to each candidate's
  ``scores`` dict. The endpoint URL is configured in full by the user to
  accommodate different provider path conventions (e.g. ``/rerank`` vs
  ``/reranks``).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def build_search_answer(candidates: list[dict]) -> str:
    """Format re-ranked candidates as a ReMe-style search answer.

    Produces the same format as ReMe's score formatter::

        ========== path:start-end [...] ==========
        text content...

    Missing score components are rendered as ``<key>=-``.

    Each candidate is expected to have ``path``, ``start_line``, ``end_line``,
    ``text``, and optionally ``scores`` — these are the fields ReMe 0.4's
    ``memory_search`` returns in ``metadata["results"]``.  ``.get()`` is used
    so that missing fields produce a degraded entry rather than a crash.
    """
    lines: list[str] = []
    for c in candidates:
        scores: dict[str, float] = c.get("scores", {})
        parts = [f"score={scores.get('score', 0.0):.4f}"]
        for key in ("vector", "keyword", "rerank"):
            val = scores.get(key)
            parts.append(f"{key}={val:.4f}" if val is not None else f"{key}=-")
        path = c.get("path", "?")
        start = c.get("start_line", "?")
        end = c.get("end_line", "?")
        header = (
            f"========== {path}:{start}-{end}"
            f" [{' '.join(parts)}] =========="
        )
        lines.append(header)
        lines.append(c.get("text", ""))
    return "\n".join(lines)


# pylint: disable=too-many-return-statements,too-many-branches
async def rerank(
    query: str,
    candidates: list[dict],
    *,
    api_key: str,
    endpoint_url: str,
    model_name: str,
    top_n: int | None = None,
    text_truncation: int = 500,
) -> list[dict]:
    """Re-rank *candidates* by relevance to *query* via a rerank API.

    Each candidate **must** be a dict with at least ``text`` and ``path`` keys.
    A ``scores`` dict (possibly empty) is expected; the rerank score is merged
    into it under the ``rerank`` key.

    *endpoint_url* must be the full endpoint URL (path included), because
    different providers use different paths (e.g. SiliconFlow ``/rerank``,
    DashScope ``/reranks``).

    Returns at most *top_n* candidates ordered by ``relevance_score``
    descending.  On any failure the original *candidates* (truncated to
    *top_n*) are returned so the caller always progresses.

    The function tolerates responses that contain fewer items than the input
    document set — many providers only return the requested top-N.
    """
    if not candidates:
        return candidates

    if not endpoint_url:
        logger.warning("[rerank] endpoint_url not configured")
        return candidates[:top_n] if top_n else candidates

    if not query:
        return candidates[:top_n] if top_n else candidates

    url = endpoint_url.rstrip("/")

    texts = [c.get("text", "")[:text_truncation] for c in candidates]

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
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("[rerank] API timeout")
        return candidates[:top_n] if top_n else candidates
    except httpx.RequestError as exc:
        logger.warning("[rerank] HTTP error: %s", exc)
        return candidates[:top_n] if top_n else candidates
    except Exception as exc:
        logger.warning("[rerank] unexpected error: %s", exc)
        return candidates[:top_n] if top_n else candidates

    raw_results = data.get("results", [])
    if not raw_results:
        logger.warning("[rerank] empty results; using original order")
        return candidates[:top_n] if top_n else candidates

    # Build (index, score) pairs — provider-agnostic key lookup.
    scored: list[tuple[int, float]] = []
    for i, item in enumerate(raw_results):
        score = item.get("relevance_score") or item.get("score") or 0.0
        idx = item.get("index", i)
        scored.append((idx, float(score)))

    scored.sort(key=lambda x: x[1], reverse=True)

    reranked: list[dict] = []
    for idx, score_val in scored:
        if 0 <= idx < len(candidates):
            c = dict(candidates[idx])
            c["scores"] = {**(c.get("scores") or {}), "rerank": score_val}
            reranked.append(c)

    if not reranked:
        logger.warning("[rerank] no valid indices; using original order")
        return candidates[:top_n] if top_n else candidates

    if top_n and len(reranked) > top_n:
        reranked = reranked[:top_n]

    logger.info(
        "[rerank] reordered %d -> %d results with model=%s",
        len(candidates),
        len(reranked),
        model_name,
    )
    return reranked

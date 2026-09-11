# -*- coding: utf-8 -*-
"""Reranking and search-response reconstruction for ReMe memory."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from ...config.config import (
    RerankerConfig,
    load_agent_config_async,
)

logger = logging.getLogger(__name__)

RerankResults = Callable[[str, Any, RerankerConfig], Awaitable[None]]
CallReranker = Callable[
    [str, list[str], RerankerConfig],
    Awaitable[list[int] | None],
]


async def load_reranker_config(agent_id: str) -> RerankerConfig | None:
    """Load the currently enabled reranker configuration."""
    try:
        agent_config = await load_agent_config_async(agent_id)
        config = getattr(
            agent_config.running.reme_light_memory_config,
            "reranker_config",
            None,
        )
        if config is not None and config.enabled and config.model_name:
            return config
    except Exception:
        logger.warning("[rerank] failed to load config", exc_info=True)
    return None


async def call_reranker_api(
    query: str,
    documents: list[str],
    config: RerankerConfig,
) -> list[int] | None:
    """Return document indices ordered by an OpenAI-compatible reranker."""
    if not config.base_url:
        logger.warning("[rerank] base_url not configured")
        return None
    if not query or not documents:
        return None

    url = f"{config.base_url.rstrip('/')}/rerank"
    payload = {
        "model": config.model_name,
        "query": query,
        "documents": documents,
    }
    try:
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        if "results" not in data:
            logger.warning("[rerank] unexpected response format: %s", data)
            return None
        scored = [
            (item["index"], item.get("relevance_score", 0.0))
            for item in data["results"]
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        ordered = [index for index, _score in scored]
        logger.info("[rerank] API responded with %d results", len(ordered))
        return ordered
    except httpx.TimeoutException:
        logger.warning("[rerank] API timed out after %ss", config.timeout)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "[rerank] HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text[:500],
        )
    except Exception:
        logger.warning("[rerank] unexpected error", exc_info=True)
    return None


async def rerank_search_results(
    query: str,
    response: Any,
    config: RerankerConfig,
    call_reranker: CallReranker = call_reranker_api,
) -> None:
    """Reorder response metadata using validated reranker indices."""
    results = response.metadata.get("results")
    if not results or len(results) <= 1:
        return
    documents = [result.get("text", "")[:500] for result in results]
    new_order = await call_reranker(query, documents, config)
    if not new_order or len(new_order) != len(results):
        return
    if set(new_order) != set(range(len(results))):
        logger.warning(
            "[rerank] API returned invalid indices: %s for %d results",
            new_order,
            len(results),
        )
        return
    response.metadata["results"] = [results[index] for index in new_order]
    logger.info(
        "[rerank] reordered %d results with model=%s",
        len(results),
        config.model_name,
    )


def format_scores_for_header(
    score: float,
    scores: dict[str, float],
) -> str:
    """Format a ReMe-compatible score header."""
    parts = [f"score={score:.4f}"]
    if "vector" in scores and "keyword" in scores:
        for key in ("vector", "keyword"):
            value = scores.get(key)
            if value is not None:
                parts.append(f"{key}={value:.4f}")
    return " ".join(parts)


def extract_score(result: dict) -> float:
    """Extract a fused score from serialized ReMe chunk data."""
    scores = result.get("scores", {})
    if isinstance(scores, dict) and "score" in scores:
        return scores["score"]
    return result.get("score", 0.0)


def rebuild_search_answer_with_expansions(
    results: list[dict],
    link_expansion: dict[str, dict],
) -> str:
    """Rebuild a ReMe answer from result and expansion metadata."""
    from reme.utils import render_expansion_lines

    answer: list[str] = []
    for result in results:
        path = result.get("path", "")
        start_line = result.get("start_line", 0)
        end_line = result.get("end_line", 0)
        score = extract_score(result)
        score_text = format_scores_for_header(
            score,
            result.get("scores", {}),
        )
        header = (
            f"========== {path}:{start_line}-{end_line} "
            f"[{score_text}] =========="
        )
        answer.append(f"{header}\n{result.get('text', '')}")
        expansion = link_expansion.get(path, {})
        if expansion:
            answer.extend(render_expansion_lines(expansion))
    return "\n".join(answer)


def parse_answer_into_sections(answer: str) -> dict[str, str]:
    """Parse a ReMe answer into path-and-line keyed sections."""
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []
    for line in answer.split("\n"):
        if line.startswith("=========="):
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines)
            rest = line.removeprefix("==========").strip()
            bracket_index = rest.find("[")
            current_key = (
                rest[:bracket_index].strip()
                if bracket_index > 0
                else (rest.split()[0] if rest else None)
            )
            current_lines = [line]
        elif current_key is not None:
            current_lines.append(line)
    if current_key is not None:
        sections[current_key] = "\n".join(current_lines)
    return sections


def reconstruct_answer_from_sections(
    sections: dict[str, str],
    results: list[dict],
) -> str:
    """Reconstruct an answer in result order, preserving known sections."""
    answer: list[str] = []
    for result in results:
        path = result.get("path", "")
        start_line = result.get("start_line", 0)
        end_line = result.get("end_line", 0)
        key = f"{path}:{start_line}-{end_line}"
        section = sections.get(key)
        if section is None:
            score_text = format_scores_for_header(
                extract_score(result),
                result.get("scores", {}),
            )
            header = f"========== {key} [{score_text}] =========="
            section = f"{header}\n{result.get('text', '')}"
        answer.append(section)
    return "\n".join(answer)


async def rerank_and_cap_response(
    query: str,
    response: Any,
    cap: int,
    config: RerankerConfig | None,
    rerank_results: RerankResults,
) -> None:
    """Rerank, cap and rebuild one mutable ReMe search response."""
    metadata = getattr(response, "metadata", None)
    results = (
        metadata.get("results") if response.success and metadata else None
    )
    if not results:
        return
    link_expansion = metadata.get("link_expansion", {})
    original_answer = str(response.answer or "")
    sections = (
        parse_answer_into_sections(original_answer) if original_answer else {}
    )
    reordered = False
    if config and len(results) > 1:
        try:
            before = list(results)
            await rerank_results(query, response, config)
            results = response.metadata["results"]
            reordered = results != before
        except Exception:
            logger.warning(
                "[rerank] failed, using original order",
                exc_info=True,
            )
    truncated = len(results) > cap
    if truncated:
        results = results[:cap]
        response.metadata["results"] = results
    if reordered or truncated:
        response.answer = (
            reconstruct_answer_from_sections(sections, results)
            if sections
            else rebuild_search_answer_with_expansions(results, link_expansion)
        )

# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-branches,too-many-statements
"""Provider search aggregation, fallback, and result deduplication."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from utils.logger import setup_logger

from ..triage import _clean_query
from .adapters import _search_dashscope_web_search_image_visuals
from .adapters import _search_dashscope_web
from .adapters import _search_tavily
from .adapters import _search_tavily_visuals
from .config import dashscope_api_key as _dashscope_web_search_image_api_key
from .config import (
    dashscope_web_search_api_key as _dashscope_web_search_api_key,
)
from .config import (
    is_retryable_visual_search_error as _is_retryable_visual_search_error,
)
from .config import (
    dashscope_native_search_unavailable_reason as _dashscope_native_search_unavailable_reason,
)
from .config import tavily_api_key as _tavily_api_key
from .config import (
    visual_search_min_results_for_fallback as _visual_search_min_results_for_fallback,
)
from .config import (
    visual_search_provider_order as _visual_search_provider_order,
)

DEFAULT_MAX_SOURCES = 6
DEFAULT_TIMEOUT = 60.0
DEFAULT_TEXT_SEARCH_TIMEOUT = 60.0
DEFAULT_TEXT_SEARCH_RETRIES = 1
DEFAULT_VISUAL_SEARCH_TIMEOUT = 120.0
DEFAULT_VISUAL_SEARCH_RETRIES = 1
USER_AGENT = "QwenPaw-Creator/0.1 web-grounding"
logger = setup_logger("services.web_grounding.providers.search")


def _dedupe_sources(
    sources: list[dict[str, Any]],
    max_sources: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for source in sources:
        url = str(source.get("url") or "").strip()
        if url:
            key = f"url:{url.casefold()}"
        else:
            metadata = (
                str(source.get(field) or "").strip().casefold()
                for field in ("title", "query", "provider", "snippet")
            )
            key = "metadata:" + "\x1f".join(metadata)
            if key == "metadata:\x1f\x1f\x1f":
                continue
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(source)
        if len(deduped) >= max_sources:
            break
    return deduped


def _dedupe_visual_sources(
    sources: list[dict[str, Any]],
    max_sources: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for source in sources:
        url = str(source.get("url") or "").strip()
        key = url.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(source)
        if len(deduped) >= max_sources:
            break
    for index, source in enumerate(deduped, start=1):
        source["index"] = index
    return deduped


def _dedupe_visual_sources_with_query_coverage(
    sources: list[dict[str, Any]],
    *,
    query_order: list[str],
    max_sources: int,
) -> list[dict[str, Any]]:
    """Prefer one candidate per visual query before filling globally."""
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []

    def add(source: dict[str, Any]) -> bool:
        url = str(source.get("url") or "").strip()
        key = url.lower()
        if not key or key in seen:
            return False
        seen.add(key)
        selected.append(source)
        return len(selected) >= max_sources

    for query in query_order:
        clean_query = _clean_query(query)
        if not clean_query:
            continue
        for source in sources:
            if _clean_query(source.get("query")) != clean_query:
                continue
            if add(source):
                break
        if len(selected) >= max_sources:
            break
    if len(selected) < max_sources:
        for source in sources:
            if add(source):
                break
    for index, source in enumerate(selected, start=1):
        source["index"] = index
    return selected


async def search_web(
    query: str,
    *,
    max_sources: int = DEFAULT_MAX_SOURCES,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run Tavily first, then fall back to DashScope/Qwen web search."""
    query = _clean_query(query)
    if not query:
        return {
            "query": query,
            "sources": [],
            "issues": ["empty_query"],
            "provider": "",
            "providers": [],
            "providers_attempted": [],
        }
    logger.info(
        "Web grounding search started query=%r max_sources=%d timeout=%s",
        query,
        max_sources,
        timeout,
    )
    headers = {"User-Agent": USER_AGENT}
    issues: list[str] = []
    providers: list[str] = []
    providers_attempted: list[str] = []
    sources: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        if _tavily_api_key():
            providers_attempted.append("tavily")
            try:
                sources = await _search_tavily(client, query, max_sources)
            except Exception as exc:
                issues.append(f"tavily:{exc.__class__.__name__}: {exc}")
                logger.warning(
                    "Web grounding provider failed query=%r provider=tavily error=%s",
                    query,
                    exc,
                )
            if sources:
                providers.append("tavily")
            else:
                issues.append("tavily:no_text_sources")
        else:
            issues.append("tavily_api_key_missing")
            logger.info(
                "Web grounding provider skipped query=%r provider=tavily reason=api_key_missing",
                query,
            )

        if not sources:
            native_search_key = _dashscope_web_search_api_key()
            native_search_issue = _dashscope_native_search_unavailable_reason(
                api_key_override=native_search_key,
            )
            if native_search_key and not native_search_issue:
                providers_attempted.append("dashscope_web_search")
                effective_timeout = max(
                    float(timeout),
                    DEFAULT_TEXT_SEARCH_TIMEOUT,
                )
                last_exc: Exception | None = None
                async with httpx.AsyncClient(
                    timeout=effective_timeout,
                    follow_redirects=True,
                    headers=headers,
                ) as dashscope_client:
                    for attempt in range(DEFAULT_TEXT_SEARCH_RETRIES + 1):
                        try:
                            sources = await _search_dashscope_web(
                                dashscope_client,
                                query,
                                max_sources,
                            )
                            if sources and attempt:
                                issues.append(
                                    f"dashscope_web_search:retry_succeeded:{attempt + 1}",
                                )
                            break
                        except Exception as exc:
                            last_exc = exc
                            retryable = _is_retryable_visual_search_error(exc)
                            logger.warning(
                                "Web grounding provider failed query=%r provider=dashscope_web_search attempt=%d/%d retryable=%s error=%s",
                                query,
                                attempt + 1,
                                DEFAULT_TEXT_SEARCH_RETRIES + 1,
                                retryable,
                                exc,
                            )
                            if (
                                not retryable
                                or attempt >= DEFAULT_TEXT_SEARCH_RETRIES
                            ):
                                break
                            await asyncio.sleep(0.25 * (attempt + 1))
                if last_exc is not None and not sources:
                    issues.append(
                        f"dashscope_web_search:{last_exc.__class__.__name__}: {last_exc}",
                    )
                    if _is_retryable_visual_search_error(last_exc):
                        issues.append("dashscope_web_search:retry_exhausted")
                if sources:
                    providers.append("dashscope_web_search")
                else:
                    issues.append("dashscope_web_search:no_text_sources")
            else:
                issues.append(
                    "dashscope_web_search_api_key_missing"
                    if not native_search_key
                    else f"dashscope_web_search:{native_search_issue}",
                )
                logger.info(
                    "Web grounding provider skipped query=%r provider=dashscope_web_search reason=%s",
                    query,
                    native_search_issue or "api_key_missing",
                )
    sources = _dedupe_sources(sources, max_sources=max_sources)
    logger.info(
        "Web grounding search completed query=%r providers=%s sources=%d issues=%d",
        query,
        ",".join(providers),
        len(sources),
        len(issues),
    )
    return {
        "query": query,
        "sources": sources,
        "issues": issues,
        "provider": providers[-1] if providers else "",
        "providers": providers,
        "providers_attempted": providers_attempted,
    }


async def search_visual_refs(
    query: str,
    *,
    max_sources: int = DEFAULT_MAX_SOURCES,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run configured image/reference search providers for one query."""
    query = _clean_query(query)
    if not query:
        return {
            "query": query,
            "visual_sources": [],
            "issues": ["empty_query"],
            "provider": "",
            "providers": [],
        }
    providers = _visual_search_provider_order()
    min_results = _visual_search_min_results_for_fallback()
    effective_timeout = max(float(timeout), DEFAULT_VISUAL_SEARCH_TIMEOUT)
    logger.info(
        "Visual grounding search started query=%r providers=%s max_sources=%d timeout=%s",
        query,
        ",".join(providers),
        max_sources,
        effective_timeout,
    )
    headers = {"User-Agent": USER_AGENT}
    issues: list[str] = []
    collected: list[dict[str, Any]] = []
    used_providers: list[str] = []
    attempted_providers: list[str] = []
    if not providers:
        if not _tavily_api_key():
            issues.append("tavily_api_key_missing")
        native_search_key = _dashscope_web_search_image_api_key()
        native_search_issue = _dashscope_native_search_unavailable_reason(
            api_key_override=native_search_key,
        )
        issues.append(
            "dashscope_web_search_image_api_key_missing"
            if not native_search_key
            else f"dashscope_web_search_image:{native_search_issue}",
        )
    async with httpx.AsyncClient(
        timeout=effective_timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        for provider in providers:
            remaining = max_sources - len(
                _dedupe_visual_sources(collected, max_sources=max_sources),
            )
            if remaining <= 0:
                break
            provider_sources: list[dict[str, Any]]
            if provider == "tavily":
                if not _tavily_api_key():
                    issues.append("tavily_api_key_missing")
                    logger.info(
                        "Visual grounding provider skipped query=%r provider=tavily reason=api_key_missing",
                        query,
                    )
                    continue
                attempted_providers.append(provider)
                try:
                    provider_sources = await _search_tavily_visuals(
                        client,
                        query,
                        remaining,
                    )
                except Exception as exc:
                    provider_sources = []
                    issues.append(
                        f"tavily_images:{exc.__class__.__name__}: {exc}",
                    )
                    logger.warning(
                        "Visual grounding provider failed query=%r provider=tavily error=%s",
                        query,
                        exc,
                    )
            elif provider == "dashscope_web_search_image":
                native_search_key = _dashscope_web_search_image_api_key()
                native_search_issue = (
                    _dashscope_native_search_unavailable_reason(
                        api_key_override=native_search_key,
                    )
                )
                if not native_search_key or native_search_issue:
                    issues.append(
                        "dashscope_web_search_image_api_key_missing"
                        if not native_search_key
                        else f"dashscope_web_search_image:{native_search_issue}",
                    )
                    logger.info(
                        "Visual grounding provider skipped query=%r provider=dashscope_web_search_image reason=%s",
                        query,
                        native_search_issue or "api_key_missing",
                    )
                    continue
                attempted_providers.append(provider)
                last_exc: BaseException | None = None
                provider_sources = []
                for attempt in range(DEFAULT_VISUAL_SEARCH_RETRIES + 1):
                    try:
                        provider_sources = (
                            await _search_dashscope_web_search_image_visuals(
                                client,
                                query,
                                remaining,
                            )
                        )
                        if attempt:
                            issues.append(
                                f"dashscope_web_search_image:retry_succeeded:{attempt + 1}",
                            )
                        break
                    except Exception as exc:
                        last_exc = exc
                        retryable = _is_retryable_visual_search_error(exc)
                        final_attempt = (
                            attempt >= DEFAULT_VISUAL_SEARCH_RETRIES
                        )
                        logger.warning(
                            "Visual grounding provider failed query=%r provider=dashscope_web_search_image attempt=%d/%d retryable=%s error=%s",
                            query,
                            attempt + 1,
                            DEFAULT_VISUAL_SEARCH_RETRIES + 1,
                            retryable,
                            exc,
                        )
                        if final_attempt or not retryable:
                            break
                        await asyncio.sleep(1.0)
                if last_exc is not None and (not provider_sources):
                    issues.append(
                        f"dashscope_web_search_image:{last_exc.__class__.__name__}: {last_exc}",
                    )
                    if _is_retryable_visual_search_error(last_exc):
                        issues.append(
                            "dashscope_web_search_image:retry_exhausted",
                        )
            else:
                issues.append(f"unknown_visual_provider:{provider}")
                continue
            if provider_sources:
                used_providers.append(provider)
                collected.extend(provider_sources)
                deduped_count = len(
                    _dedupe_visual_sources(collected, max_sources=max_sources),
                )
                if deduped_count >= min_results:
                    break
            else:
                issues.append(f"{provider}:no_visual_sources")
    visual_sources = _dedupe_visual_sources(collected, max_sources=max_sources)
    logger.info(
        "Visual grounding search completed query=%r providers=%s visual_sources=%d issues=%d",
        query,
        ",".join(used_providers),
        len(visual_sources),
        len(issues),
    )
    return {
        "query": query,
        "visual_sources": visual_sources,
        "issues": issues,
        "provider": used_providers[-1] if used_providers else "",
        "providers": used_providers,
        "providers_attempted": attempted_providers,
    }

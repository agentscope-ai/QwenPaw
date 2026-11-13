# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Provider transport and response-normalization adapters."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

from utils.logger import setup_logger

from ..common import clean_text as _clean_text
from ..triage import _clean_query
from .config import dashscope_api_key as _dashscope_web_search_image_api_key
from .config import dashscope_base_url as _dashscope_web_search_image_base_url
from .config import dashscope_model as _dashscope_web_search_image_model
from .config import (
    dashscope_web_search_api_key as _dashscope_web_search_api_key,
)
from .config import (
    dashscope_web_search_base_url as _dashscope_web_search_base_url,
)
from .config import dashscope_web_search_model as _dashscope_web_search_model
from .config import responses_url_from_base as _responses_url_from_base
from .config import serper_api_key as _serper_api_key
from .config import tavily_api_key as _tavily_api_key
from .serper import SERPER_IMAGES_URL
from .serper import SERPER_LENS_URL
from .serper import SERPER_LENS_EMPTY_RESULT_ATTEMPTS
from .serper import SERPER_LENS_EMPTY_RETRY_BACKOFF_SECONDS
from .serper import SERPER_LENS_MAX_ATTEMPTS
from .serper import SERPER_RETRY_BACKOFF_CAP_SECONDS
from .serper import SERPER_SCRAPE_MAX_ATTEMPTS
from .serper import SERPER_SCRAPE_URL
from .serper import SERPER_SEARCH_URL
from .serper import SERPER_SEARCH_MAX_ATTEMPTS

DEFAULT_MAX_SOURCES = 6
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
logger = setup_logger(__name__)
# Region defaults mirror the upstream qwen-mm-plugins Serper client, whose
# request shape is the field-proven reference for this integration.
SERPER_SEARCH_PARAMS = {"gl": "us", "hl": "en", "location": "United States"}
SERPER_LENS_PARAMS = {"gl": "us", "hl": "en"}
SERPER_EXTRACT_CONTENT_LIMIT = 8000


class SerperAuthenticationError(RuntimeError):
    """Serper rejected the configured API credential."""


def _is_retryable_serper_response(response: httpx.Response) -> bool:
    return response.status_code == 429 or response.status_code >= 500


async def _post_serper_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    api_key: str,
    payload: dict[str, Any],
    max_attempts: int,
) -> dict[str, Any]:
    """POST JSON with bounded retries for transient Serper failures."""
    attempts = max(1, int(max_attempts))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = await client.post(
                url,
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code in {401, 403}:
                raise SerperAuthenticationError(
                    "Serper rejected SERPER_API_KEY "
                    f"(HTTP {response.status_code} Unauthorized); verify that "
                    "the key is active and belongs to an enabled Serper "
                    "account",
                )
            if _is_retryable_serper_response(response):
                response.raise_for_status()
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if not _is_retryable_serper_response(exc.response):
                raise
        if attempt >= attempts:
            break
        await asyncio.sleep(
            min(
                SERPER_RETRY_BACKOFF_CAP_SECONDS,
                float(2 ** (attempt - 1)),
            ),
        )
    raise RuntimeError(
        f"Serper request failed after {attempts} attempts: {last_error}",
    )


def _tavily_safe_search_enabled() -> bool:
    """Tavily rejects safe_search outside enterprise plans; opt-in only."""
    raw = os.environ.get("TAVILY_SAFE_SEARCH", "")
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


async def _search_tavily(
    client: httpx.AsyncClient,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    api_key = _tavily_api_key()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")
    payload: dict[str, Any] = {
        "query": query,
        "search_depth": os.environ.get("TAVILY_SEARCH_DEPTH", "basic"),
        "chunks_per_source": 3,
        "max_results": limit,
        "topic": "general",
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_image_descriptions": False,
        "include_favicon": False,
        "auto_parameters": False,
    }
    if _tavily_safe_search_enabled():
        payload["safe_search"] = True
    response = await client.post(
        os.environ.get("TAVILY_SEARCH_URL", TAVILY_SEARCH_URL),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    response.raise_for_status()
    payload = response.json()
    results = []
    for item in payload.get("results", [])[:limit]:
        title = _clean_text(item.get("title"), max_chars=180)
        url = str(item.get("url") or "").strip()
        snippet = _clean_text(item.get("content"), max_chars=500)
        if title and url:
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "provider": "tavily",
                    "query": query,
                    "score": item.get("score"),
                },
            )
    return results


async def _search_serper(
    client: httpx.AsyncClient,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    api_key = _serper_api_key()
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is not configured")
    payload = await _post_serper_json(
        client,
        os.environ.get("SERPER_SEARCH_URL", SERPER_SEARCH_URL),
        api_key=api_key,
        payload={
            "q": query,
            **SERPER_SEARCH_PARAMS,
            "num": max(1, min(limit, DEFAULT_MAX_SOURCES)),
        },
        max_attempts=SERPER_SEARCH_MAX_ATTEMPTS,
    )
    results = []
    for item in payload.get("organic", [])[:limit]:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), max_chars=180)
        url = str(item.get("link") or item.get("url") or "").strip()
        snippet = _clean_text(item.get("snippet"), max_chars=500)
        if title and url:
            result = {
                "title": title,
                "url": url,
                "snippet": snippet,
                "provider": "serper",
                "query": query,
                "score": None,
            }
            date = _clean_text(item.get("date"), max_chars=80)
            if date:
                result["date"] = date
            results.append(result)
    return results


def _image_url_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in (
        "url",
        "image_url",
        "imageUrl",
        "src",
        "thumbnail_url",
        "thumbnailUrl",
    ):
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


def _normalize_tavily_images(
    payload: dict[str, Any],
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    raw_images: list[Any] = []
    if isinstance(payload, dict):
        top_level = payload.get("images")
        if isinstance(top_level, list):
            raw_images.extend(top_level)
        results = payload.get("results")
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, dict):
                    continue
                for image in result.get("images") or []:
                    if isinstance(image, dict):
                        raw_images.append(
                            {
                                **image,
                                "source_url": image.get("source_url")
                                or result.get("url")
                                or "",
                                "title": image.get("title")
                                or result.get("title")
                                or image.get("description")
                                or "",
                            },
                        )
                    else:
                        raw_images.append(
                            {
                                "url": image,
                                "source_url": result.get("url") or "",
                                "title": result.get("title") or "",
                            },
                        )
    visual_sources: list[dict[str, Any]] = []
    for item in raw_images:
        url = _image_url_from_value(item)
        if not url:
            continue
        if isinstance(item, dict):
            title = _clean_text(
                item.get("title")
                or item.get("description")
                or item.get("alt")
                or "",
                max_chars=180,
            )
            source_url = str(
                item.get("source_url")
                or item.get("sourceUrl")
                or item.get("page_url")
                or "",
            ).strip()
            thumbnail_url = str(
                item.get("thumbnail_url") or item.get("thumbnailUrl") or "",
            ).strip()
        else:
            title = ""
            source_url = ""
            thumbnail_url = ""
        visual_sources.append(
            {
                "url": url,
                "thumbnail_url": thumbnail_url,
                "source_url": source_url,
                "title": title,
                "provider": "tavily",
                "query": query,
            },
        )
        if len(visual_sources) >= limit:
            break
    return visual_sources


def _source_url_from_value(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in (
        "source_url",
        "sourceUrl",
        "page_url",
        "pageUrl",
        "link",
        "origin_url",
        "originUrl",
    ):
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


def _thumbnail_url_from_value(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in (
        "thumbnail_url",
        "thumbnailUrl",
        "thumbnail",
        "thumb_url",
        "thumbUrl",
    ):
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


def _dashscope_web_search_image_items(payload: Any) -> list[Any]:
    raw_items: list[Any] = []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if isinstance(payload, list):
        raw_items.extend(payload)
        return raw_items
    if not isinstance(payload, dict):
        return []

    for key in ("images", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_items.extend(value)

    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type and item_type != "web_search_image_call":
                continue
            tool_output = item.get("output")
            if tool_output is None:
                continue
            raw_items.extend(_dashscope_web_search_image_items(tool_output))
    elif isinstance(output, dict):
        raw_items.extend(_dashscope_web_search_image_items(output))

    return raw_items


def _normalize_dashscope_web_search_images(
    payload: dict[str, Any],
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    visual_sources: list[dict[str, Any]] = []
    for item in _dashscope_web_search_image_items(payload):
        url = _image_url_from_value(item)
        if not url:
            continue
        if isinstance(item, dict):
            title = _clean_text(
                item.get("title")
                or item.get("description")
                or item.get("alt")
                or item.get("name")
                or "",
                max_chars=180,
            )
            source_url = _source_url_from_value(item)
            thumbnail_url = _thumbnail_url_from_value(item)
            raw_index = item.get("index")
        else:
            title = ""
            source_url = ""
            thumbnail_url = ""
            raw_index = None
        visual_sources.append(
            {
                "url": url,
                "thumbnail_url": thumbnail_url,
                "source_url": source_url,
                "title": title,
                "provider": "dashscope_web_search_image",
                "query": query,
                "provider_index": raw_index,
            },
        )
        if len(visual_sources) >= limit:
            break
    return visual_sources


def _normalize_dashscope_web_search_sources(
    payload: dict[str, Any],
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Normalize Responses API ``web_search_call.action.sources`` entries."""
    sources: list[dict[str, Any]] = []
    output = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(output, list):
        return sources
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action")
        raw_sources = (
            action.get("sources") if isinstance(action, dict) else None
        )
        if not isinstance(raw_sources, list):
            continue
        for raw_source in raw_sources:
            if isinstance(raw_source, str):
                url = raw_source.strip()
                title = ""
                snippet = ""
            elif isinstance(raw_source, dict):
                url = str(
                    raw_source.get("url")
                    or raw_source.get("link")
                    or raw_source.get("source_url")
                    or "",
                ).strip()
                title = _clean_text(
                    raw_source.get("title")
                    or raw_source.get("name")
                    or raw_source.get("site_name")
                    or "",
                    max_chars=180,
                )
                snippet = _clean_text(
                    raw_source.get("snippet")
                    or raw_source.get("content")
                    or raw_source.get("description")
                    or "",
                    max_chars=500,
                )
            else:
                continue
            if not url:
                continue
            sources.append(
                {
                    "title": title or url,
                    "url": url,
                    "snippet": snippet,
                    "provider": "dashscope_web_search",
                    "query": query,
                },
            )
            if len(sources) >= limit:
                return sources
    return sources


async def _search_tavily_visuals(
    client: httpx.AsyncClient,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    api_key = _tavily_api_key()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")
    payload: dict[str, Any] = {
        "query": query,
        "search_depth": os.environ.get("TAVILY_SEARCH_DEPTH", "basic"),
        "chunks_per_source": 1,
        "max_results": max(1, min(limit, DEFAULT_MAX_SOURCES)),
        "topic": "general",
        "include_answer": False,
        "include_raw_content": False,
        "include_images": True,
        "include_image_descriptions": True,
        "include_favicon": False,
        "auto_parameters": False,
    }
    if _tavily_safe_search_enabled():
        payload["safe_search"] = True
    response = await client.post(
        os.environ.get("TAVILY_SEARCH_URL", TAVILY_SEARCH_URL),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    response.raise_for_status()
    return _normalize_tavily_images(response.json(), query, limit)


def _normalize_serper_images(
    payload: dict[str, Any],
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    raw_images = payload.get("images") if isinstance(payload, dict) else None
    if not isinstance(raw_images, list):
        return []
    visual_sources: list[dict[str, Any]] = []
    for item in raw_images:
        url = _image_url_from_value(item)
        if not url:
            continue
        if isinstance(item, dict):
            title = _clean_text(
                item.get("title") or item.get("source") or "",
                max_chars=180,
            )
            source_url = _source_url_from_value(item)
            thumbnail_url = _thumbnail_url_from_value(item)
        else:
            title = ""
            source_url = ""
            thumbnail_url = ""
        visual_sources.append(
            {
                "url": url,
                "thumbnail_url": thumbnail_url,
                "source_url": source_url,
                "title": title,
                "provider": "serper",
                "query": query,
            },
        )
        if len(visual_sources) >= limit:
            break
    return visual_sources


async def _search_serper_visuals(
    client: httpx.AsyncClient,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    api_key = _serper_api_key()
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is not configured")
    payload = await _post_serper_json(
        client,
        os.environ.get("SERPER_IMAGES_URL", SERPER_IMAGES_URL),
        api_key=api_key,
        payload={
            "q": query,
            **SERPER_SEARCH_PARAMS,
            "num": max(1, min(limit, DEFAULT_MAX_SOURCES)),
        },
        max_attempts=SERPER_SEARCH_MAX_ATTEMPTS,
    )
    return _normalize_serper_images(payload, query, limit)


def _normalize_serper_lens_matches(
    payload: dict[str, Any],
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    raw_matches = payload.get("organic") if isinstance(payload, dict) else None
    if not isinstance(raw_matches, list):
        return []
    visual_sources: list[dict[str, Any]] = []
    for item in raw_matches:
        url = _image_url_from_value(item)
        if not url:
            continue
        if isinstance(item, dict):
            title = _clean_text(
                item.get("title") or item.get("source") or "",
                max_chars=180,
            )
            source_url = _source_url_from_value(item)
            thumbnail_url = _thumbnail_url_from_value(item)
        else:
            title = ""
            source_url = ""
            thumbnail_url = ""
        visual_sources.append(
            {
                "url": url,
                "thumbnail_url": thumbnail_url,
                "source_url": source_url,
                "title": title,
                "provider": "serper_lens",
                "query": query,
            },
        )
        if len(visual_sources) >= limit:
            break
    return visual_sources


async def _search_serper_lens(
    client: httpx.AsyncClient,
    image_url: str,
    limit: int,
    *,
    query: str = "",
) -> list[dict[str, Any]]:
    """Reverse image search (Google Lens via Serper).

    Serper Lens only accepts a public http(s) ``url`` payload; the caller is
    responsible for resolving local media to a temporary public URL first.
    Successful responses with an empty ``organic`` array are treated as a
    transient upstream miss and retried a bounded number of times.
    """
    api_key = _serper_api_key()
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is not configured")
    lens_url = os.environ.get("SERPER_LENS_URL", SERPER_LENS_URL)
    attempts = max(1, int(SERPER_LENS_EMPTY_RESULT_ATTEMPTS))
    for attempt in range(1, attempts + 1):
        payload = await _post_serper_json(
            client,
            lens_url,
            api_key=api_key,
            payload={"url": image_url, **SERPER_LENS_PARAMS},
            max_attempts=SERPER_LENS_MAX_ATTEMPTS,
        )
        matches = _normalize_serper_lens_matches(payload, query, limit)
        if matches or attempt >= attempts:
            return matches
        logger.info(
            "Serper Lens returned no matches; retrying attempt=%d/%d",
            attempt,
            attempts,
        )
        await asyncio.sleep(SERPER_LENS_EMPTY_RETRY_BACKOFF_SECONDS)
    return []


async def _extract_serper_pages(
    client: httpx.AsyncClient,
    urls: list[str],
    *,
    goal: str = "",
    content_limit: int = SERPER_EXTRACT_CONTENT_LIMIT,
) -> list[dict[str, Any]]:
    """Extract bounded page content with Serper's scrape endpoint."""
    api_key = _serper_api_key()
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is not configured")
    extracted: list[dict[str, Any]] = []
    for url in urls:
        payload = await _post_serper_json(
            client,
            os.environ.get("SERPER_SCRAPE_URL", SERPER_SCRAPE_URL),
            api_key=api_key,
            payload={"url": url, "includeMarkdown": True},
            max_attempts=SERPER_SCRAPE_MAX_ATTEMPTS,
        )
        content = str(payload.get("markdown") or payload.get("text") or "")
        if not content.strip():
            continue
        extracted.append(
            {
                "title": _clean_text(
                    payload.get("title") or url,
                    max_chars=180,
                ),
                "url": url,
                "snippet": _clean_text(content, max_chars=500),
                "content": content[: max(1, int(content_limit))],
                "goal": _clean_text(goal, max_chars=300),
                "provider": "serper_scrape",
                "query": _clean_text(goal, max_chars=300),
                "score": None,
            },
        )
    return extracted


async def _search_dashscope_web_search_image_visuals(
    client: httpx.AsyncClient,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    api_key = _dashscope_web_search_image_api_key()
    if not api_key:
        raise RuntimeError("DashScope API key is not configured")
    response = await client.post(
        _responses_url_from_base(_dashscope_web_search_image_base_url()),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": _dashscope_web_search_image_model(),
            "input": query,
            "tools": [{"type": "web_search_image"}],
        },
    )
    response.raise_for_status()
    return _normalize_dashscope_web_search_images(
        response.json(),
        query,
        limit,
    )


async def _search_dashscope_web(
    client: httpx.AsyncClient,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    query = _clean_query(query)
    if not query:
        return []
    api_key = _dashscope_web_search_api_key()
    if not api_key:
        raise RuntimeError("DashScope API key is not configured")
    response = await client.post(
        _responses_url_from_base(_dashscope_web_search_base_url()),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": _dashscope_web_search_model(),
            "input": f"Search the web for: {query}",
            "tools": [{"type": "web_search"}],
            "store": False,
        },
    )
    response.raise_for_status()
    return _normalize_dashscope_web_search_sources(
        response.json(),
        query,
        limit,
    )

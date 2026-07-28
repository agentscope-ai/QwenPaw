# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Provider transport and response-normalization adapters."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

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
from .config import tavily_api_key as _tavily_api_key

DEFAULT_MAX_SOURCES = 6
TAVILY_SEARCH_URL = "https://api.tavily.com/search"


async def _search_tavily(
    client: httpx.AsyncClient,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    api_key = _tavily_api_key()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")
    response = await client.post(
        os.environ.get("TAVILY_SEARCH_URL", TAVILY_SEARCH_URL),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
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
            "safe_search": True,
        },
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
    response = await client.post(
        os.environ.get("TAVILY_SEARCH_URL", TAVILY_SEARCH_URL),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
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
            "safe_search": True,
        },
    )
    response.raise_for_status()
    return _normalize_tavily_images(response.json(), query, limit)


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

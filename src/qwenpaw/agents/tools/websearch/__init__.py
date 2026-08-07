# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Pluggable web search providers for the ``web_search`` tool.

``SearchProvider`` is the abstraction that lets QwenPaw swap the search
backend without touching the tool surface.  The active provider is chosen
via the ``QWENPAW_WEBSEARCH_PROVIDER`` environment variable
(``anysearch`` by default, ``tavily`` to fall back to the legacy
keyless backend).
"""

from __future__ import annotations

import logging
import os
import ssl

from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_TIMEOUT = 30


def _is_ssl_error(exc: BaseException) -> bool:
    """Check if exc (or its cause chain) is SSL-related."""
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, ssl.SSLError):
            return True
        if "SSL" in type(cur).__name__:
            return True
        cur = cur.__cause__
    return False


async def _post(
    url: str,
    headers: dict,
    payload: dict,
) -> dict:
    """Async HTTP POST with SSL-verification fallback."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as first_exc:
        if not _is_ssl_error(first_exc):
            raise
        logger.warning("SSL verify failed for %s, retrying", url)
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def format_search_results(results: list[dict]) -> str:
    """Format search results into readable text."""
    if not results:
        return "No results found."
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        lines.append(f"[{i}] {title}")
        lines.append(f"    URL: {url}")
        if content:
            lines.append(f"    {content}")
        lines.append("")
    return "\n".join(lines).rstrip()


class SearchProvider(ABC):
    """Abstract web search backend."""

    name = ""

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Return a list of ``{title, url, snippet, content}`` dicts."""
        raise NotImplementedError


class TavilyProvider(SearchProvider):
    """Legacy Tavily keyless search backend."""

    name = "tavily"

    _SEARCH_URL = "https://api.tavily.com/search"

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        payload = {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
        data = await _post(
            self._SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Tavily-Access-Mode": "keyless",
            },
            payload=payload,
        )
        return list(data.get("results") or [])


class AnySearchProvider(SearchProvider):
    """AnySearch REST search backend (https://api.anysearch.com)."""

    name = "anysearch"

    _SEARCH_URL = "https://api.anysearch.com/v1/search"

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get("ANYSEARCH_API_KEY", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "query": query,
            "max_results": max_results,
        }
        data = await _post(
            self._SEARCH_URL,
            headers=headers,
            payload=payload,
        )
        return list((data.get("data") or {}).get("results") or [])


def get_search_provider() -> SearchProvider:
    """Return the active search provider selected by env var."""
    choice = os.environ.get("QWENPAW_WEBSEARCH_PROVIDER", "").strip().lower()
    if choice == "tavily":
        return TavilyProvider()
    return AnySearchProvider()


__all__ = [
    "SearchProvider",
    "TavilyProvider",
    "AnySearchProvider",
    "get_search_provider",
    "format_search_results",
]

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

import os

from abc import ABC, abstractmethod

import httpx

_TIMEOUT = 30


async def _post(
    url: str,
    headers: dict,
    payload: dict,
) -> dict:
    """Async HTTP POST with certificate validation always on."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
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
    """Return the active search provider selected by env var.

    Defaults to ``tavily`` (the legacy keyless backend). Set
    ``QWENPAW_WEBSEARCH_PROVIDER=anysearch`` to use AnySearch.
    Unknown values raise ``ValueError`` instead of silently routing.
    """
    choice = os.environ.get("QWENPAW_WEBSEARCH_PROVIDER", "").strip().lower()
    if choice in {"", "tavily"}:
        return TavilyProvider()
    if choice == "anysearch":
        return AnySearchProvider()
    raise ValueError(
        f"Unknown QWENPAW_WEBSEARCH_PROVIDER: {choice!r} "
        "(expected 'tavily' or 'anysearch')",
    )


__all__ = [
    "SearchProvider",
    "TavilyProvider",
    "AnySearchProvider",
    "get_search_provider",
    "format_search_results",
]

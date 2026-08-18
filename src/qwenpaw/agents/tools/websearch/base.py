# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Shared search-provider base: transport, formatting, abstract backend."""

from __future__ import annotations

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


__all__ = ["SearchProvider", "format_search_results", "_post"]

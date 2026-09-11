# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Tavily keyless search backend (legacy default)."""

from __future__ import annotations

from .base import SearchProvider, _post


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


__all__ = ["TavilyProvider"]

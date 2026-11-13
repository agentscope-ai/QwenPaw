# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Tavily search backend (keyless default, optional authenticated)."""

from __future__ import annotations

import logging

import httpx

from .base import SearchProvider, _post
from .credentials import read_optional_api_key

logger = logging.getLogger(__name__)

_CREDENTIAL_REF = "tool/web_search/tavily"
_FALLBACK_STATUS_CODES = frozenset({401, 429, 432})


async def _current_agent_tavily_key() -> str:
    """Read the optional Tavily API key from the current agent's
    credential store (``tool/web_search/tavily``).

    Empty string means "no key configured" — the provider then stays on
    the keyless default path.
    """
    return (await read_optional_api_key(_CREDENTIAL_REF)) or ""


class TavilyProvider(SearchProvider):
    """Tavily search backend.

    Default path is keyless anonymous REST (``X-Tavily-Access-Mode:
    keyless``). When the agent has a Tavily API key in the credential
    store, authenticated Bearer requests are preferred; on HTTP 401 /
    429 / 432 the provider logs a warning and falls back to keyless.
    """

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
        api_key = await _current_agent_tavily_key()
        if api_key:
            try:
                data = await _post(
                    self._SEARCH_URL,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    payload=payload,
                )
                return list(data.get("results") or [])
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in _FALLBACK_STATUS_CODES:
                    raise
                logger.warning(
                    "Tavily authenticated search failed with HTTP %s; "
                    "falling back to keyless mode",
                    status,
                )
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

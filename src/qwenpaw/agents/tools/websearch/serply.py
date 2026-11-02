# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Serply REST search backend (https://serply.io), Google results."""

from __future__ import annotations

from .base import SearchProvider, _get
from .credentials import read_optional_api_key

_CREDENTIAL_REF = "tool/web_search/serply"


async def _current_agent_serply_key() -> str:
    """Read the Serply API key from the current agent's credential store
    (``tool/web_search/serply``, written by the Console).

    Returns ``""`` when no key is stored.
    """
    return (await read_optional_api_key(_CREDENTIAL_REF)) or ""


class SerplyProvider(SearchProvider):
    """Serply REST search backend (https://serply.io), Google results."""

    name = "serply"

    _SEARCH_URL = "https://api.serply.io/v1/search"

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        api_key = await _current_agent_serply_key()
        if not api_key:
            raise ValueError(
                "Serply API key is not configured. Set it in the Console "
                "(Tools > web_search) or select another provider.",
            )
        data = await _get(
            self._SEARCH_URL,
            headers={"X-Api-Key": api_key},
            params={"q": query, "num": max_results},
        )
        results: list[dict] = []
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "")
            if not url:
                continue
            snippet = str(item.get("description") or "")
            results.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": url,
                    "snippet": snippet,
                    "content": snippet,
                },
            )
        return results[:max_results]


__all__ = ["SerplyProvider", "_current_agent_serply_key"]

# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""DeepSeek search backend (official Search API).

Endpoint: ``POST https://api.deepseek.com/v1/tools/search``
Docs: https://api-docs.deepseek.com/zh-cn/guides/search

Billing is per successful request (the request must be HTTP 200 **and**
return a non-empty ``results`` array); failures and empty results are
free. The API key is read from the agent credential store under
``tool/web_search/deepseek`` so it never lives in plaintext config.
"""

from __future__ import annotations

import logging

import httpx

from .base import SearchProvider, _post
from .credentials import read_optional_api_key

logger = logging.getLogger(__name__)

_CREDENTIAL_REF = "tool/web_search/deepseek"
_MAX_RESULTS_LIMIT = 50


async def _current_agent_deepseek_key() -> str:
    """Read the DeepSeek API key from the current agent's credential store."""
    return (await read_optional_api_key(_CREDENTIAL_REF)) or ""


def _normalise(item: dict) -> dict:
    """Map DeepSeek result fields onto the shared ``SearchProvider`` shape.

    ``format_search_results`` only consumes ``title`` / ``url`` /
    ``content``; ``summary`` is used as the body when full page content
    was not requested. ``date`` / ``authority`` / ``rerank_score`` are
    carried through so callers can filter on freshness or credibility.
    """
    summary = str(item.get("summary") or "")
    content = str(item.get("content") or "")
    return {
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or ""),
        "snippet": str(item.get("snippet") or ""),
        "content": content or summary,
        "date": item.get("date"),
        "authority": item.get("authority"),
        "rerank_score": item.get("rerank_score"),
    }


class DeepSeekProvider(SearchProvider):
    """DeepSeek official search backend (paid, structured results)."""

    name = "deepseek"

    _SEARCH_URL = "https://api.deepseek.com/v1/tools/search"

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        api_key = await _current_agent_deepseek_key()
        if not api_key:
            raise ValueError(
                "DeepSeek web search requires an API key. Store it under "
                f"credential ref {_CREDENTIAL_REF!r}, or switch "
                "tools.builtin_tools.web_search.config.provider back to "
                "'tavily'."
            )

        count = max(1, min(int(max_results or 5), _MAX_RESULTS_LIMIT))
        payload = {
            "query": query,
            "count": count,
            "need_content": False,
        }
        try:
            data = await _post(
                self._SEARCH_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                payload=payload,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise ValueError(
                    "DeepSeek web search rejected the API key (HTTP 401).",
                ) from exc
            if status == 402:
                raise ValueError(
                    "DeepSeek web search: account balance is insufficient "
                    "(HTTP 402). Top up or switch provider to 'tavily'.",
                ) from exc
            if status == 429:
                raise ValueError(
                    "DeepSeek web search hit the account-level QPS limit "
                    "(HTTP 429: 5 requests/second). Retry after a pause.",
                ) from exc
            raise

        return [_normalise(item) for item in (data.get("results") or [])]


__all__ = ["DeepSeekProvider", "_normalise"]

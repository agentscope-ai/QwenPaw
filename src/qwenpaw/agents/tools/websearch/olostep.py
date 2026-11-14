# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Olostep search backend (https://docs.olostep.com/api-reference/searches/create)."""

from __future__ import annotations

import httpx

from .base import SearchProvider, _post
from .credentials import read_optional_api_key

_CREDENTIAL_REF = "tool/web_search/olostep"
# The Searches API accepts ``limit`` from 1 to 25 and answers HTTP 400
# outside that range.
_MAX_LIMIT = 25


async def _current_agent_olostep_key() -> str:
    """Read the Olostep API key from the current agent's credential store
    (``tool/web_search/olostep``). Empty string means no key."""
    return (await read_optional_api_key(_CREDENTIAL_REF)) or ""


def _http_error_message(response: httpx.Response) -> str:
    """Build a readable error from a non-2xx Olostep response."""
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = ""
    if isinstance(body, dict):
        detail = str(body.get("detail") or body.get("message") or "")
    detail = detail.strip().rstrip(".")
    message = f"Olostep search error ({response.status_code})"
    if detail:
        message += f": {detail}"
    if response.status_code == 401:
        message += ". Check the Olostep API key in the web_search tool config."
    elif response.status_code == 429:
        message += ". Rate limit reached; try again in a moment."
    return message


class OlostepProvider(SearchProvider):
    """Olostep Searches API backend.

    An API key is required and is sent as a Bearer header. Results are the
    link snippets from ``result.links``; pages are not scraped.
    """

    name = "olostep"

    _SEARCH_URL = "https://api.olostep.com/v1/searches"

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        api_key = await _current_agent_olostep_key()
        if not api_key:
            raise ValueError(
                "Olostep search needs an API key; add one in the web_search "
                "tool config (create one at "
                "https://www.olostep.com/dashboard/api-keys).",
            )
        payload = {
            "query": query,
            "limit": min(max(max_results, 1), _MAX_LIMIT),
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
            raise ValueError(_http_error_message(exc.response)) from exc
        items = (data.get("result") or {}).get("links") or []
        return [
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("description") or "",
                "content": item.get("description") or "",
            }
            for item in items
        ]


__all__ = ["OlostepProvider"]

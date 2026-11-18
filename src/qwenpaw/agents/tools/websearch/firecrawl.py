# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Firecrawl search backend (https://docs.firecrawl.dev/api-reference/endpoint/search)."""

from __future__ import annotations

import logging

import httpx

from .base import SearchProvider, _post
from .credentials import read_optional_api_key

logger = logging.getLogger(__name__)

_CREDENTIAL_REF = "tool/web_search/firecrawl"
# Firecrawl answers 401 for a missing, malformed or revoked key. Keyless
# search may still work, so one anonymous retry is allowed for it.
_AUTH_FALLBACK_STATUS_CODES = frozenset({401})


async def _current_agent_firecrawl_key() -> str:
    """Read the optional Firecrawl API key from the current agent's
    credential store (``tool/web_search/firecrawl``).

    Empty string means "no key configured" and the request goes out
    without an ``Authorization`` header.
    """
    return (await read_optional_api_key(_CREDENTIAL_REF)) or ""


def _http_error_message(response: httpx.Response, has_key: bool) -> str:
    """Build a readable error from a non-2xx Firecrawl response."""
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = str(body.get("error") or "") if isinstance(body, dict) else ""
    message = f"Firecrawl search error ({response.status_code})"
    if detail:
        message += f": {detail}"
    if response.status_code == 429:
        if has_key:
            message += ". Rate limit reached; try again in a moment."
        else:
            message += (
                ". The keyless limit may be reached; "
                "add a Firecrawl API key in the web_search tool config."
            )
    return message


class FirecrawlProvider(SearchProvider):
    """Firecrawl search backend.

    The API key is optional. When one is stored, authenticated requests are
    preferred; on HTTP 401 the provider logs a warning and retries
    once without the ``Authorization`` header.
    """

    name = "firecrawl"

    _SEARCH_URL = "https://api.firecrawl.dev/v2/search"

    async def _request(
        self,
        payload: dict,
        api_key: str,
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        data = await _post(
            self._SEARCH_URL,
            headers=headers,
            payload=payload,
        )
        if data.get("success") is False:
            raise ValueError(
                f"Firecrawl search failed: {data.get('error') or data!r}",
            )
        return data

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        payload = {
            "query": query,
            "limit": max_results,
            "sources": ["web"],
            "origin": "qwenpaw",
        }
        api_key = await _current_agent_firecrawl_key()
        try:
            data = await self._request(payload, api_key)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if not api_key or status not in _AUTH_FALLBACK_STATUS_CODES:
                raise ValueError(
                    _http_error_message(exc.response, bool(api_key)),
                ) from exc
            logger.warning(
                "Firecrawl authenticated search failed with HTTP %s; "
                "retrying once without an API key",
                status,
            )
            try:
                data = await self._request(payload, "")
            except httpx.HTTPStatusError as retry_exc:
                raise ValueError(
                    _http_error_message(retry_exc.response, False),
                ) from retry_exc
        items = (data.get("data") or {}).get("web") or []
        return [
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("description") or "",
                "content": item.get("description") or "",
            }
            for item in items
        ]


__all__ = ["FirecrawlProvider"]

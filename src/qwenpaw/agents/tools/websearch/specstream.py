# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""SpecStream search backend (https://specstream.ai/docs/search-api)."""

from __future__ import annotations

import httpx

from .base import SearchProvider, _get
from .credentials import read_optional_api_key

_CREDENTIAL_REF = "tool/web_search/specstream"


async def _current_agent_specstream_key() -> str:
    """Read the SpecStream API key from the current agent's credential
    store (``tool/web_search/specstream``). Empty string means no key."""
    return (await read_optional_api_key(_CREDENTIAL_REF)) or ""


def _http_error_message(response: httpx.Response) -> str:
    """Build a readable error from a non-2xx SpecStream response."""
    status = response.status_code
    message = f"SpecStream search error ({status})"
    if status == 401:
        message += ". The API key is missing or invalid; check the key in the web_search tool config."
    elif status == 402:
        message += ". The account balance is empty; add balance at specstream.ai."
    elif status == 503:
        retry_after = response.headers.get("Retry-After")
        message += ". The service is busy"
        if retry_after:
            message += f"; retry after {retry_after} seconds"
        message += "."
    return message


class SpecStreamProvider(SearchProvider):
    """SpecStream Search API backend.

    An API key is required and is sent as a Bearer header. The API has no
    result-count parameter, so the result list is trimmed locally.
    """

    name = "specstream"

    _SEARCH_URL = "https://api.specstream.ai/v1/web-search"

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        api_key = await _current_agent_specstream_key()
        if not api_key:
            raise ValueError(
                "SpecStream search needs an API key; "
                "add one in the web_search tool config.",
            )
        try:
            body = await _get(
                self._SEARCH_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                params={"q": query},
            )
        except httpx.HTTPStatusError as exc:
            raise ValueError(_http_error_message(exc.response)) from exc
        data = body.get("data") or {}
        results: list[dict] = []
        answer = data.get("answer")
        if isinstance(answer, dict) and answer.get("value"):
            value = str(answer["value"])
            results.append(
                {
                    "title": "Answer",
                    "url": answer.get("page") or "",
                    "snippet": value,
                    "content": value,
                },
            )
        for item in data.get("sources") or []:
            snippet = item.get("snippet") or ""
            results.append(
                {
                    "title": item.get("title") or "",
                    "url": item.get("url") or "",
                    "snippet": snippet,
                    "content": snippet,
                },
            )
        return results[: max(max_results, 0)]


__all__ = ["SpecStreamProvider"]

# -*- coding: utf-8 -*-
"""Tests for the pluggable web search provider abstraction."""

from __future__ import annotations

import pytest

from qwenpaw.agents.tools.websearch import (
    AnySearchProvider,
    SearchProvider,
    TavilyProvider,
    format_search_results,
    get_search_provider,
)


def test_get_search_provider_defaults_to_anysearch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QWENPAW_WEBSEARCH_PROVIDER", raising=False)
    assert isinstance(get_search_provider(), AnySearchProvider)


def test_get_search_provider_selects_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_WEBSEARCH_PROVIDER", "tavily")
    assert isinstance(get_search_provider(), TavilyProvider)


def test_providers_are_search_provider_subclasses() -> None:
    assert issubclass(AnySearchProvider, SearchProvider)
    assert issubclass(TavilyProvider, SearchProvider)
    assert AnySearchProvider.name == "anysearch"
    assert TavilyProvider.name == "tavily"


@pytest.mark.asyncio
async def test_anysearch_provider_parses_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url, headers, payload):
        assert url == "https://api.anysearch.com/v1/search"
        assert "Authorization" not in headers
        assert payload == {"query": "qwen", "max_results": 3}
        return {
            "code": 0,
            "data": {
                "results": [
                    {
                        "title": "T",
                        "url": "https://example.com",
                        "snippet": "S",
                        "content": "C",
                    },
                ],
            },
        }

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch._post",
        fake_post,
    )
    provider = AnySearchProvider()
    results = await provider.search("qwen", max_results=3)
    assert results == [
        {
            "title": "T",
            "url": "https://example.com",
            "snippet": "S",
            "content": "C",
        },
    ]


@pytest.mark.asyncio
async def test_anysearch_provider_sends_key_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url, headers, payload):
        assert headers["Authorization"] == "Bearer sk-test"
        return {"code": 0, "data": {"results": []}}

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch._post",
        fake_post,
    )
    monkeypatch.setenv("ANYSEARCH_API_KEY", "sk-test")
    provider = AnySearchProvider()
    assert await provider.search("qwen") == []


@pytest.mark.asyncio
async def test_tavily_provider_uses_keyless_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url, headers, payload):
        assert url == "https://api.tavily.com/search"
        assert headers["X-Tavily-Access-Mode"] == "keyless"
        return {"results": [{"title": "T", "url": "u", "content": "c"}]}

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch._post",
        fake_post,
    )
    provider = TavilyProvider()
    results = await provider.search("qwen")
    assert results == [{"title": "T", "url": "u", "content": "c"}]


def test_format_search_results() -> None:
    text = format_search_results(
        [
            {"title": "A", "url": "https://a.com", "content": "body"},
            {"title": "B", "url": "https://b.com"},
        ],
    )
    assert "[1] A" in text
    assert "URL: https://a.com" in text
    assert "[2] B" in text
    assert format_search_results([]) == "No results found."

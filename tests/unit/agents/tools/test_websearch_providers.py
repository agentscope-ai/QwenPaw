# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Tests for the pluggable web search provider abstraction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.tools.websearch import (
    AnySearchProvider,
    SearchProvider,
    TavilyProvider,
    format_search_results,
    get_search_provider,
)


def _agent_config_with_provider(provider: str | None):
    """Build a minimal stand-in for ``AgentProfileConfig`` whose
    ``tools.builtin_tools["web_search"].config`` carries the given
    provider choice (``None`` means the web_search tool config is absent
    entirely, exercising the "not configured" fallback)."""
    if provider is None:
        builtin_tools = {}
    else:
        builtin_tools = {
            "web_search": SimpleNamespace(config={"provider": provider}),
        }
    return SimpleNamespace(
        tools=SimpleNamespace(builtin_tools=builtin_tools),
    )


def test_get_search_provider_defaults_to_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.get_current_agent_id",
        lambda: "default",
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.load_agent_config",
        lambda agent_id: _agent_config_with_provider(None),
    )
    assert isinstance(get_search_provider(), TavilyProvider)


def test_get_search_provider_selects_anysearch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.get_current_agent_id",
        lambda: "default",
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.load_agent_config",
        lambda agent_id: _agent_config_with_provider("anysearch"),
    )
    assert isinstance(get_search_provider(), AnySearchProvider)


def test_get_search_provider_selects_tavily_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.get_current_agent_id",
        lambda: "default",
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.load_agent_config",
        lambda agent_id: _agent_config_with_provider("tavily"),
    )
    assert isinstance(get_search_provider(), TavilyProvider)


def test_get_search_provider_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.get_current_agent_id",
        lambda: "default",
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.load_agent_config",
        lambda agent_id: _agent_config_with_provider("bogus"),
    )
    with pytest.raises(ValueError):
        get_search_provider()


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
        "qwenpaw.agents.tools.websearch.anysearch._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._current_agent_anysearch_key",
        AsyncMock(return_value=""),
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
        del url, payload
        assert headers["Authorization"] == "Bearer sk-test"
        return {"code": 0, "data": {"results": []}}

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._current_agent_anysearch_key",
        AsyncMock(return_value="sk-test"),
    )
    provider = AnySearchProvider()
    assert await provider.search("qwen") == []


@pytest.mark.asyncio
async def test_tavily_provider_uses_keyless_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url, headers, payload):
        del payload
        assert url == "https://api.tavily.com/search"
        assert headers["X-Tavily-Access-Mode"] == "keyless"
        return {"results": [{"title": "T", "url": "u", "content": "c"}]}

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.tavily._post",
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

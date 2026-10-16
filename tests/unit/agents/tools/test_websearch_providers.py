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
    SerplyProvider,
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


def test_get_search_provider_selects_serply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.get_current_agent_id",
        lambda: "default",
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.load_agent_config",
        lambda agent_id: _agent_config_with_provider("serply"),
    )
    assert isinstance(get_search_provider(), SerplyProvider)


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
    assert issubclass(SerplyProvider, SearchProvider)
    assert issubclass(TavilyProvider, SearchProvider)
    assert AnySearchProvider.name == "anysearch"
    assert SerplyProvider.name == "serply"
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
async def test_serply_provider_parses_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url, headers, params):
        assert url == "https://api.serply.io/v1/search"
        assert headers == {"X-Api-Key": "sp-test"}
        assert params == {"q": "qwen", "num": 2}
        return {
            "results": [
                {
                    "title": "T",
                    "link": "https://example.com",
                    "description": "D",
                    "position": 1,
                },
                {"title": "no link", "description": "skipped"},
                "not a dict",
                {
                    "title": "U",
                    "link": "https://example.org",
                    "description": "E",
                },
                {
                    "title": "beyond num",
                    "link": "https://example.net",
                },
            ],
        }

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.serply._get",
        fake_get,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.serply._current_agent_serply_key",
        AsyncMock(return_value="sp-test"),
    )
    provider = SerplyProvider()
    results = await provider.search("qwen", max_results=2)
    assert results == [
        {
            "title": "T",
            "url": "https://example.com",
            "snippet": "D",
            "content": "D",
        },
        {
            "title": "U",
            "url": "https://example.org",
            "snippet": "E",
            "content": "E",
        },
    ]


@pytest.mark.asyncio
async def test_serply_provider_requires_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_get = AsyncMock()
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.serply._get",
        fake_get,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.serply._current_agent_serply_key",
        AsyncMock(return_value=""),
    )
    with pytest.raises(ValueError, match="Serply API key"):
        await SerplyProvider().search("qwen")
    fake_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_serply_key_is_empty_without_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.agents.tools.websearch.serply import (
        _current_agent_serply_key,
    )

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.credentials.get_current_workspace_dir",
        lambda: None,
    )
    assert await _current_agent_serply_key() == ""


@pytest.mark.asyncio
async def test_tavily_provider_uses_keyless_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url, headers, payload):
        del payload
        assert url == "https://api.tavily.com/search"
        assert headers["X-Tavily-Access-Mode"] == "keyless"
        assert "Authorization" not in headers
        return {"results": [{"title": "T", "url": "u", "content": "c"}]}

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.tavily._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.tavily._current_agent_tavily_key",
        AsyncMock(return_value=""),
    )
    provider = TavilyProvider()
    results = await provider.search("qwen")
    assert results == [{"title": "T", "url": "u", "content": "c"}]


@pytest.mark.asyncio
async def test_tavily_provider_uses_bearer_when_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url, headers, payload):
        del url, payload
        assert headers["Authorization"] == "Bearer tvly-test"
        assert "X-Tavily-Access-Mode" not in headers
        return {"results": [{"title": "A", "url": "u", "content": "c"}]}

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.tavily._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.tavily._current_agent_tavily_key",
        AsyncMock(return_value="tvly-test"),
    )
    provider = TavilyProvider()
    assert await provider.search("qwen") == [
        {"title": "A", "url": "u", "content": "c"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 432])
async def test_tavily_provider_falls_back_to_keyless_on_quota_errors(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    import httpx

    calls: list[dict] = []

    async def fake_post(url, headers, payload):
        del url, payload
        calls.append(dict(headers))
        if "Authorization" in headers:
            request = httpx.Request("POST", "https://api.tavily.com/search")
            response = httpx.Response(status, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {status}",
                request=request,
                response=response,
            )
        assert headers["X-Tavily-Access-Mode"] == "keyless"
        return {"results": [{"title": "K", "url": "u", "content": "c"}]}

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.tavily._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.tavily._current_agent_tavily_key",
        AsyncMock(return_value="tvly-bad"),
    )
    provider = TavilyProvider()
    results = await provider.search("qwen")
    assert results == [{"title": "K", "url": "u", "content": "c"}]
    assert len(calls) == 2
    assert calls[0]["Authorization"] == "Bearer tvly-bad"
    assert calls[1]["X-Tavily-Access-Mode"] == "keyless"


@pytest.mark.asyncio
async def test_tavily_provider_does_not_fallback_on_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    async def fake_post(url, headers, payload):
        del url, headers, payload
        request = httpx.Request("POST", "https://api.tavily.com/search")
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError(
            "HTTP 500",
            request=request,
            response=response,
        )

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.tavily._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.tavily._current_agent_tavily_key",
        AsyncMock(return_value="tvly-bad"),
    )
    provider = TavilyProvider()
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await provider.search("qwen")
    assert exc_info.value.response.status_code == 500


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


@pytest.mark.asyncio
async def test_read_optional_api_key_returns_none_without_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.agents.tools.websearch.credentials import (
        read_optional_api_key,
    )

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.credentials.get_current_workspace_dir",
        lambda: None,
    )
    assert await read_optional_api_key("tool/web_search/tavily") is None


@pytest.mark.asyncio
async def test_read_optional_api_key_reads_via_sync_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from qwenpaw.agents.tools.websearch.credentials import (
        read_optional_api_key,
    )
    from qwenpaw.drivers.credentials.store import AsyncCredentialStore
    from qwenpaw.drivers.credentials.types import CredentialRecord

    cred_path = tmp_path / "credentials.yaml"
    store = AsyncCredentialStore(cred_path)
    await store.put(
        CredentialRecord(
            ref="tool/web_search/tavily",
            kind="static",
            secrets={"api_key": "tvly-from-store"},
        ),
    )

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.credentials.get_current_workspace_dir",
        lambda: tmp_path,
    )
    assert await read_optional_api_key("tool/web_search/tavily") == (
        "tvly-from-store"
    )
    assert await read_optional_api_key("tool/web_search/missing") is None

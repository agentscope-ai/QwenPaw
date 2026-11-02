# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Tests for the DeepSeek search provider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from qwenpaw.agents.tools.websearch import (
    DeepSeekProvider,
    SearchProvider,
    TavilyProvider,
    get_search_provider,
)


def _agent_config_with_provider(provider: str | None):
    if provider is None:
        builtin_tools = {}
    else:
        builtin_tools = {
            "web_search": SimpleNamespace(config={"provider": provider}),
        }
    return SimpleNamespace(
        tools=SimpleNamespace(builtin_tools=builtin_tools),
    )


def test_get_search_provider_selects_deepseek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.get_current_agent_id",
        lambda: "default",
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.factory.load_agent_config",
        lambda agent_id: _agent_config_with_provider("deepseek"),
    )
    assert isinstance(get_search_provider(), DeepSeekProvider)


def test_deepseek_provider_is_search_provider() -> None:
    assert issubclass(DeepSeekProvider, SearchProvider)
    assert DeepSeekProvider.name == "deepseek"
    assert not issubclass(DeepSeekProvider, TavilyProvider)


@pytest.mark.asyncio
async def test_deepseek_provider_maps_structured_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url, headers, payload):
        assert url == "https://api.deepseek.com/v1/tools/search"
        assert headers["Authorization"] == "Bearer sk-test"
        assert payload == {"query": "qwen", "count": 3, "need_content": False}
        return {
            "results": [
                {
                    "title": "T",
                    "url": "https://example.com",
                    "snippet": "S",
                    "summary": "LONG",
                    "content": "",
                    "date": "2026-06-01T00:00:00+00:00",
                    "authority": 3,
                    "rerank_score": 2.4,
                },
            ],
        }

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.deepseek._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.deepseek._current_agent_deepseek_key",
        AsyncMock(return_value="sk-test"),
    )

    results = await DeepSeekProvider().search("qwen", max_results=3)

    assert results == [
        {
            "title": "T",
            "url": "https://example.com",
            "snippet": "S",
            "content": "LONG",
            "date": "2026-06-01T00:00:00+00:00",
            "authority": 3,
            "rerank_score": 2.4,
        },
    ]


@pytest.mark.asyncio
async def test_deepseek_provider_prefers_content_over_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url, headers, payload):
        del url, headers, payload
        return {
            "results": [
                {"title": "T", "url": "u", "summary": "S", "content": "FULL"},
            ],
        }

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.deepseek._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.deepseek._current_agent_deepseek_key",
        AsyncMock(return_value="sk-test"),
    )

    results = await DeepSeekProvider().search("qwen")
    assert results[0]["content"] == "FULL"


@pytest.mark.asyncio
async def test_deepseek_provider_requires_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.deepseek._current_agent_deepseek_key",
        AsyncMock(return_value=""),
    )
    with pytest.raises(ValueError, match="requires an API key"):
        await DeepSeekProvider().search("qwen")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        (401, "rejected the API key"),
        (402, "balance is insufficient"),
        (429, "QPS limit"),
    ],
)
async def test_deepseek_provider_explains_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    fragment: str,
) -> None:
    async def fake_post(url, headers, payload):
        del url, headers, payload
        request = httpx.Request("POST", "https://api.deepseek.com/v1/tools/search")
        response = httpx.Response(status, request=request)
        raise httpx.HTTPStatusError("boom", request=request, response=response)

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.deepseek._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.deepseek._current_agent_deepseek_key",
        AsyncMock(return_value="sk-test"),
    )

    with pytest.raises(ValueError, match=fragment):
        await DeepSeekProvider().search("qwen")


@pytest.mark.asyncio
async def test_deepseek_provider_clamps_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict = {}

    async def fake_post(url, headers, payload):
        del url, headers
        seen.update(payload)
        return {"results": []}

    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.deepseek._post",
        fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.deepseek._current_agent_deepseek_key",
        AsyncMock(return_value="sk-test"),
    )

    await DeepSeekProvider().search("qwen", max_results=999)
    assert seen["count"] == 50

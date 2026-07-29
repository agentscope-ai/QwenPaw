# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,protected-access,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
import asyncio
import json

import httpx
import pytest

from services.web_grounding import pipeline as web_grounding
from services.web_grounding import common as grounding_common
from services.web_grounding import staging
from services.web_grounding import triage as grounding_triage
from services.web_grounding import verification
from services.web_grounding import visual_jobs as grounding_visual_jobs
from services.web_grounding.providers import config as provider_config
from services.web_grounding.providers import search as provider_search
from services.web_grounding.providers import adapters


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


def test_dashscope_model_falls_back_when_model_config_raises(monkeypatch):
    def fail_model_name():
        raise RuntimeError("model config is not initialized")

    monkeypatch.setattr(
        provider_config.model_config,
        "get_text_model_name",
        fail_model_name,
    )

    assert provider_config.dashscope_model() == "qwen3.7-plus"


def test_confidence_overshoot_is_clamped_but_percentages_are_normalized():
    assert grounding_common.coerce_confidence(1.5, default=0.0) == 1.0
    assert grounding_common.coerce_confidence(85, default=0.0) == 0.85


def test_download_visual_source_enforces_streamed_size_limit():
    async def handler(request):
        assert str(request.url) == "https://img.test/large.png"
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"\x89PNG\r\n\x1a\n" + (b"x" * 32),
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError, match="too large"):
                await staging.download_visual_source(
                    client,
                    {"url": "https://img.test/large.png"},
                    max_bytes=16,
                )

    asyncio.run(run())


def test_download_visual_source_rejects_mislabeled_image_bytes():
    async def handler(request):
        assert str(request.url) == "https://img.test/not-really.jpg"
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=b"not a jpeg despite the response content type",
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError, match="invalid image bytes"):
                await staging.download_visual_source(
                    client,
                    {"url": "https://img.test/not-really.jpg"},
                    max_bytes=1024,
                )

    asyncio.run(run())


def test_download_visual_source_rejects_magic_bytes_that_cannot_decode():
    async def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=b"\xff\xd8\xffnot-a-decodable-jpeg",
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(
                ValueError,
                match="cannot be decoded as an image",
            ):
                await staging.download_visual_source(
                    client,
                    {"url": "https://img.test/corrupt.jpg"},
                    max_bytes=1024,
                )

    asyncio.run(run())


def test_detect_grounding_needs_for_explicit_search():
    result = web_grounding.detect_grounding_needs(
        "请上网查一下 2026 World Cup top players 的资料",
    )

    assert result["needs_grounding"] is True
    assert "explicit_search" in result["reasons"]
    assert result["queries"]


def test_detect_grounding_skips_self_contained_fiction():
    result = web_grounding.detect_grounding_needs("编一个虚构太空厨师的短片 prompt，风格温暖")

    assert result["needs_grounding"] is False
    assert result["queries"] == []


def test_hybrid_detector_uses_llm_for_chinese_entity(monkeypatch):
    async def fake_llm_detector(prompt, context=None, *, max_queries=3):
        assert "哈兰德" in prompt
        return {
            "needs_grounding": True,
            "need_websearch": True,
            "confidence": 0.91,
            "reasons": ["specific_real_world_entity"],
            "queries": ["Erling Haaland football profile"],
            "entities": [
                {
                    "text": "哈兰德",
                    "type": "person",
                    "canonical": "Erling Haaland",
                },
            ],
            "detector": "llm",
            "detector_issues": [],
        }

    monkeypatch.setattr(
        grounding_triage,
        "classify_grounding_needs_llm",
        fake_llm_detector,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "做一个哈兰德的球星资料短片",
            detect_only=True,
        ),
    )

    assert result["needs_grounding"] is True
    assert result["detector"] == "llm"
    assert result["queries"] == ["Erling Haaland football profile"]
    assert result["entities"][0]["canonical"] == "Erling Haaland"


def test_grounding_triage_exposes_domain_and_visual_decision(monkeypatch):
    async def fake_llm_detector(prompt, context=None, *, max_queries=3):
        assert "哈兰德" in prompt
        return {
            "needs_grounding": True,
            "need_websearch": True,
            "domain": "sports_target_player",
            "include_visuals": True,
            "confidence": 0.93,
            "reasons": ["specific_real_world_entity", "visual_identity"],
            "queries": ["Erling Haaland Norway jersey number"],
            "entities": [
                {
                    "text": "哈兰德",
                    "type": "sports_player",
                    "canonical": "Erling Haaland",
                },
            ],
            "detector": "llm",
            "detector_issues": [],
        }

    monkeypatch.setattr(
        grounding_triage,
        "classify_grounding_needs_llm",
        fake_llm_detector,
    )

    triage = asyncio.run(web_grounding.triage_grounding_request("剪辑哈兰德的国家队高光"))

    assert triage["needs_grounding"] is True
    assert triage["domain"] == "sports_target_player"
    assert triage["include_visuals"] is True
    assert triage["queries"] == ["Erling Haaland Norway jersey number"]
    assert triage["entities"][0]["type"] == "sports_player"
    assert triage["entities"][0]["visual_usage"] == "identity"
    assert triage["entities"][0]["needs_visual_grounding"] is True
    assert triage["entities"][0]["strict_identity"] is True


def test_visual_reference_terms_trigger_visual_grounding_without_llm():
    vogue = asyncio.run(
        web_grounding.triage_grounding_request(
            "做一个 Vogue Style 的时尚片头，需要高级杂志感",
            detector="heuristic",
        ),
    )
    yi_silver = asyncio.run(
        web_grounding.triage_grounding_request(
            "生成彝族银饰和传统服饰的视觉参考",
            detector="heuristic",
        ),
    )

    assert vogue["needs_grounding"] is True
    assert vogue["domain"] == "visual_style"
    assert vogue["include_visuals"] is True
    assert "visual_reference_term" in vogue["reasons"]
    assert yi_silver["needs_grounding"] is True
    assert yi_silver["domain"] == "visual_style"
    assert yi_silver["include_visuals"] is True


def test_ground_prompt_context_searches_llm_detector_queries(monkeypatch):
    async def fake_llm_detector(prompt, context=None, *, max_queries=3):
        return {
            "needs_grounding": True,
            "need_websearch": True,
            "confidence": 0.88,
            "reasons": ["specific_real_world_entity"],
            "queries": ["Erling Haaland football profile"],
            "entities": [
                {
                    "text": "哈兰德",
                    "type": "person",
                    "canonical": "Erling Haaland",
                },
            ],
            "detector": "llm",
            "detector_issues": [],
        }

    searched_queries = []

    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        searched_queries.append(query)
        return {
            "query": query,
            "issues": [],
            "sources": [
                {
                    "title": "Erling Haaland",
                    "url": "https://example.test/haaland",
                    "snippet": "Erling Haaland is a Norway international striker.",
                    "provider": "fake",
                    "query": query,
                },
            ],
        }

    monkeypatch.setattr(
        grounding_triage,
        "classify_grounding_needs_llm",
        fake_llm_detector,
    )
    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "做一个哈兰德的球星资料短片",
            include_visuals=False,
        ),
    )

    assert result["status"] == "success"
    assert searched_queries == ["Erling Haaland football profile"]
    assert "Erling Haaland" in result["grounded_context"]


def test_ground_prompt_context_can_use_heuristic_detector(monkeypatch):
    async def fail_llm_detector(*args, **kwargs):
        raise AssertionError("LLM detector should not run in heuristic mode")

    monkeypatch.setattr(
        grounding_triage,
        "classify_grounding_needs_llm",
        fail_llm_detector,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "做一个哈兰德的球星资料短片",
            detect_only=True,
            detector="heuristic",
        ),
    )

    assert result["needs_grounding"] is False
    assert result["detector"] == "heuristic"


def test_ground_prompt_context_uses_search_results(monkeypatch):
    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "sources": [
                {
                    "title": "Erling Haaland",
                    "url": "https://example.test/haaland",
                    "snippet": "Erling Haaland is a Norway international striker.",
                    "provider": "fake",
                    "query": query,
                },
            ],
        }

    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "make a grounded target-player clip",
            queries=["Erling Haaland Norway footballer"],
        ),
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["needs_grounding"] is True
    assert result["sources"][0]["index"] == 1
    assert result["facts"][0]["source_indices"] == [1]
    assert "Erling Haaland" in result["grounded_context"]


def test_detect_only_does_not_search(monkeypatch):
    async def fail_search(*args, **kwargs):
        raise AssertionError(
            "search_web should not be called in detect_only mode",
        )

    monkeypatch.setattr(web_grounding, "search_web", fail_search)
    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "latest FIFA World Cup roster",
            detect_only=True,
        ),
    )

    assert result["ok"] is True
    assert result["status"] == "detected"
    assert result["needs_grounding"] is True


def test_search_tavily_maps_response(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    payload = {
        "results": [
            {
                "title": "Erling Haaland Facts",
                "url": "https://example.test/haaland",
                "content": "Norway striker for Manchester City.",
                "score": 0.9,
            },
        ],
    }
    client = _FakeClient(payload)

    results = asyncio.run(adapters._search_tavily(client, "Erling Haaland", 3))

    assert client.calls
    assert client.calls[0][1]["headers"]["Authorization"] == "Bearer tvly-test"
    assert client.calls[0][1]["json"]["query"] == "Erling Haaland"
    assert results == [
        {
            "title": "Erling Haaland Facts",
            "url": "https://example.test/haaland",
            "snippet": "Norway striker for Manchester City.",
            "provider": "tavily",
            "query": "Erling Haaland",
            "score": 0.9,
        },
    ]


def test_search_tavily_visuals_maps_top_level_and_result_images(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    payload = {
        "images": [
            {"url": "https://img.test/top.jpg", "description": "Top image"},
        ],
        "results": [
            {
                "title": "Erling Haaland Facts",
                "url": "https://example.test/haaland",
                "images": [
                    {
                        "url": "https://img.test/result.jpg",
                        "description": "Result image",
                    },
                ],
            },
        ],
    }
    client = _FakeClient(payload)

    results = asyncio.run(
        adapters._search_tavily_visuals(client, "Erling Haaland", 3),
    )

    assert client.calls
    assert client.calls[0][1]["json"]["include_images"] is True
    assert client.calls[0][1]["json"]["include_image_descriptions"] is True
    assert [item["url"] for item in results] == [
        "https://img.test/top.jpg",
        "https://img.test/result.jpg",
    ]
    assert results[1]["source_url"] == "https://example.test/haaland"


def test_search_dashscope_web_search_image_visuals_maps_response(monkeypatch):
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")
    monkeypatch.setenv(
        "TEXT_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("TEXT_MODEL_NAME", "qwen3.7-plus")
    payload = {
        "output": [
            {
                "type": "web_search_image_call",
                "status": "completed",
                "output": (
                    '[{"index":1,"title":"Yi silver headdress",'
                    '"url":"https://img.test/yi-silver.jpg",'
                    '"source_url":"https://example.test/yi"}]'
                ),
            },
            {"type": "message", "content": []},
        ],
    }
    client = _FakeClient(payload)

    results = asyncio.run(
        adapters._search_dashscope_web_search_image_visuals(
            client,
            "彝族银饰",
            3,
        ),
    )

    assert client.calls
    assert client.calls[0][0].endswith("/compatible-mode/v1/responses")
    assert (
        client.calls[0][1]["headers"]["Authorization"]
        == "Bearer dashscope-test"
    )
    assert client.calls[0][1]["json"]["tools"] == [
        {"type": "web_search_image"},
    ]
    assert results == [
        {
            "url": "https://img.test/yi-silver.jpg",
            "thumbnail_url": "",
            "source_url": "https://example.test/yi",
            "title": "Yi silver headdress",
            "provider": "dashscope_web_search_image",
            "query": "彝族银饰",
            "provider_index": 1,
        },
    ]


def test_search_dashscope_web_maps_response_sources(monkeypatch):
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")
    monkeypatch.setenv(
        "TEXT_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("TEXT_MODEL_NAME", "qwen3.7-plus")
    client = _FakeClient(
        {
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "sources": [
                            {
                                "title": "Erling Haaland profile",
                                "url": "https://example.test/haaland",
                                "snippet": "Norwegian footballer profile.",
                            },
                            {"url": "https://example.test/haaland-stats"},
                        ],
                    },
                },
            ],
        },
    )

    results = asyncio.run(
        adapters._search_dashscope_web(
            client,
            "Erling Haaland official profile biography",
            3,
        ),
    )

    assert client.calls[0][0].endswith("/compatible-mode/v1/responses")
    assert client.calls[0][1]["json"]["tools"] == [{"type": "web_search"}]
    assert client.calls[0][1]["json"]["store"] is False
    assert results[0] == {
        "title": "Erling Haaland profile",
        "url": "https://example.test/haaland",
        "snippet": "Norwegian footballer profile.",
        "provider": "dashscope_web_search",
        "query": "Erling Haaland official profile biography",
    }
    assert results[1]["title"] == "https://example.test/haaland-stats"


def test_search_dashscope_web_cleans_query_before_request(monkeypatch):
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")
    client = _FakeClient({"output": []})

    results = asyncio.run(
        adapters._search_dashscope_web(
            client,
            "请   Erling Haaland official profile biography!!!",
            3,
        ),
    )

    assert results == []
    assert client.calls[0][1]["json"]["input"] == (
        "Search the web for: Erling Haaland official profile biography"
    )


def test_dedupe_sources_keeps_distinct_url_less_results() -> None:
    first = {
        "title": "Shared title",
        "query": "query one",
        "provider": "provider-one",
        "snippet": "first snippet",
    }
    exact_duplicate = dict(first)
    second = {
        "title": "Shared title",
        "query": "query two",
        "provider": "provider-two",
        "snippet": "second snippet",
    }

    deduped = provider_search._dedupe_sources(
        [first, exact_duplicate, second],
        max_sources=3,
    )

    assert deduped == [first, second]


def test_search_web_uses_tavily_without_dashscope_fallback(monkeypatch):
    monkeypatch.setattr(
        provider_search,
        "_tavily_api_key",
        lambda: "tavily-key",
    )
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: "dashscope-key",
    )

    async def fake_tavily(client, query, limit):
        return [
            {
                "title": "Tavily source",
                "url": "https://example.test/tavily",
                "snippet": "source",
                "provider": "tavily",
                "query": query,
            },
        ]

    async def fail_dashscope(*args, **kwargs):
        raise AssertionError("DashScope should not run when Tavily succeeds")

    monkeypatch.setattr(provider_search, "_search_tavily", fake_tavily)
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web",
        fail_dashscope,
    )

    result = asyncio.run(web_grounding.search_web("Erling Haaland"))

    assert result["provider"] == "tavily"
    assert result["providers"] == ["tavily"]
    assert result["providers_attempted"] == ["tavily"]


def test_search_web_falls_back_to_dashscope_when_tavily_missing(monkeypatch):
    monkeypatch.setattr(provider_search, "_tavily_api_key", lambda: "")
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: "dashscope-key",
    )

    async def fake_dashscope(client, query, limit):
        return [
            {
                "title": "Qwen source",
                "url": "https://example.test/qwen",
                "snippet": "source-backed biography",
                "provider": "dashscope_web_search",
                "query": query,
            },
        ]

    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web",
        fake_dashscope,
    )

    result = asyncio.run(web_grounding.search_web("Erling Haaland"))

    assert result["provider"] == "dashscope_web_search"
    assert result["providers"] == ["dashscope_web_search"]
    assert result["providers_attempted"] == ["dashscope_web_search"]
    assert result["sources"][0]["url"] == "https://example.test/qwen"
    assert "tavily_api_key_missing" in result["issues"]


def test_search_web_falls_back_to_dashscope_when_tavily_empty(monkeypatch):
    monkeypatch.setattr(
        provider_search,
        "_tavily_api_key",
        lambda: "tavily-key",
    )
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: "dashscope-key",
    )

    async def empty_tavily(client, query, limit):
        return []

    async def fake_dashscope(client, query, limit):
        return [
            {
                "title": "Qwen source",
                "url": "https://example.test/qwen",
                "snippet": "source",
                "provider": "dashscope_web_search",
                "query": query,
            },
        ]

    monkeypatch.setattr(provider_search, "_search_tavily", empty_tavily)
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web",
        fake_dashscope,
    )

    result = asyncio.run(web_grounding.search_web("Rodrigo De Paul"))

    assert result["provider"] == "dashscope_web_search"
    assert result["providers_attempted"] == ["tavily", "dashscope_web_search"]
    assert "tavily:no_text_sources" in result["issues"]


def test_search_web_retries_dashscope_timeout_with_sixty_second_client(
    monkeypatch,
):
    monkeypatch.setattr(provider_search, "_tavily_api_key", lambda: "")
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: "dashscope-key",
    )
    attempts = 0
    client_timeouts = []
    real_client = httpx.AsyncClient

    class RecordingClient(real_client):
        def __init__(self, *args, **kwargs):
            client_timeouts.append(kwargs.get("timeout"))
            super().__init__(*args, **kwargs)

    async def flaky_dashscope(client, query, limit):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("slow qwen text search")
        return [
            {
                "title": "Qwen source",
                "url": "https://example.test/qwen",
                "snippet": "source",
                "provider": "dashscope_web_search",
                "query": query,
            },
        ]

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(provider_search.httpx, "AsyncClient", RecordingClient)
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web",
        flaky_dashscope,
    )
    monkeypatch.setattr(provider_search.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        web_grounding.search_web("Erling Haaland", timeout=8.0),
    )

    assert attempts == 2
    assert client_timeouts == [8.0, 60.0]
    assert result["provider"] == "dashscope_web_search"
    assert "dashscope_web_search:retry_succeeded:2" in result["issues"]


def test_search_visual_refs_prefers_tavily_when_it_has_results(monkeypatch):
    monkeypatch.delenv("WEB_GROUNDING_IMAGE_PROVIDERS", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_VISUAL_PROVIDERS", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")

    async def fake_tavily(client, query, limit):
        return [
            {
                "url": "https://img.test/tavily.jpg",
                "title": "Tavily image",
                "provider": "tavily",
                "query": query,
            },
        ]

    async def fail_dashscope(*args, **kwargs):
        raise AssertionError(
            "DashScope fallback should not run when Tavily has results",
        )

    monkeypatch.setattr(provider_search, "_search_tavily_visuals", fake_tavily)
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web_search_image_visuals",
        fail_dashscope,
    )

    result = asyncio.run(web_grounding.search_visual_refs("Erling Haaland"))

    assert result["providers"] == ["tavily"]
    assert result["provider"] == "tavily"
    assert result["visual_sources"][0]["url"] == "https://img.test/tavily.jpg"


def test_search_visual_refs_falls_back_to_dashscope_when_tavily_empty(
    monkeypatch,
):
    monkeypatch.delenv("WEB_GROUNDING_IMAGE_PROVIDERS", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_VISUAL_PROVIDERS", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")

    async def empty_tavily(client, query, limit):
        return []

    async def fake_dashscope(client, query, limit):
        return [
            {
                "url": "https://img.test/dashscope.jpg",
                "title": "DashScope image",
                "provider": "dashscope_web_search_image",
                "query": query,
            },
        ]

    monkeypatch.setattr(
        provider_search,
        "_search_tavily_visuals",
        empty_tavily,
    )
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web_search_image_visuals",
        fake_dashscope,
    )

    result = asyncio.run(web_grounding.search_visual_refs("彝族银饰"))

    assert result["providers"] == ["dashscope_web_search_image"]
    assert result["provider"] == "dashscope_web_search_image"
    assert "tavily:no_visual_sources" in result["issues"]
    assert (
        result["visual_sources"][0]["url"] == "https://img.test/dashscope.jpg"
    )


def test_search_visual_refs_uses_dashscope_when_tavily_key_absent(monkeypatch):
    monkeypatch.delenv("WEB_GROUNDING_IMAGE_PROVIDERS", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_VISUAL_PROVIDERS", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")

    async def fail_tavily(*args, **kwargs):
        raise AssertionError(
            "Tavily should not run when no Tavily key is configured",
        )

    async def fake_dashscope(client, query, limit):
        return [
            {
                "url": "https://img.test/qwen-only.jpg",
                "title": "Qwen web search image",
                "provider": "dashscope_web_search_image",
                "query": query,
            },
        ]

    monkeypatch.setattr(provider_search, "_search_tavily_visuals", fail_tavily)
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web_search_image_visuals",
        fake_dashscope,
    )

    result = asyncio.run(
        web_grounding.search_visual_refs("Vogue editorial style"),
    )

    assert result["providers"] == ["dashscope_web_search_image"]
    assert result["provider"] == "dashscope_web_search_image"
    assert "tavily_api_key_missing" not in result["issues"]
    assert (
        result["visual_sources"][0]["url"] == "https://img.test/qwen-only.jpg"
    )


def test_search_visual_refs_retries_dashscope_timeout(monkeypatch):
    monkeypatch.delenv("WEB_GROUNDING_IMAGE_PROVIDERS", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_VISUAL_PROVIDERS", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")
    attempts = 0

    async def flaky_dashscope(client, query, limit):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("slow qwen image search")
        return [
            {
                "url": "https://img.test/haaland.jpg",
                "title": "Erling Haaland portrait",
                "provider": "dashscope_web_search_image",
                "query": query,
            },
        ]

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web_search_image_visuals",
        flaky_dashscope,
    )
    monkeypatch.setattr(provider_search.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        web_grounding.search_visual_refs("Erling Haaland portrait"),
    )

    assert attempts == 2
    assert result["providers"] == ["dashscope_web_search_image"]
    assert result["provider"] == "dashscope_web_search_image"
    assert result["visual_sources"][0]["url"] == "https://img.test/haaland.jpg"
    assert "dashscope_web_search_image:retry_succeeded:2" in result["issues"]


def test_search_visual_refs_reports_nonretryable_dashscope_error(monkeypatch):
    monkeypatch.delenv("WEB_GROUNDING_IMAGE_PROVIDERS", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_VISUAL_PROVIDERS", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")
    attempts = 0

    async def invalid_dashscope_response(client, query, limit):
        nonlocal attempts
        attempts += 1
        raise ValueError("invalid image search payload")

    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web_search_image_visuals",
        invalid_dashscope_response,
    )

    result = asyncio.run(
        web_grounding.search_visual_refs("Erling Haaland portrait"),
    )

    assert attempts == 1
    assert (
        "dashscope_web_search_image:ValueError: invalid image search payload"
        in result["issues"]
    )
    assert "dashscope_web_search_image:retry_exhausted" not in result["issues"]


def test_visual_jobs_infer_types_from_string_context_entities():
    jobs = web_grounding._expand_visual_query_jobs(
        ["Erling Haaland appearance facial features"],
        context={
            "entities": ["Erling Haaland", "Idol Producer"],
            "base_profile": {
                "Erling Haaland": "Norwegian professional footballer, tall blonde, athletic build",
                "Idol Producer": "Chinese reality TV talent show, idol trainee competition format",
            },
        },
        entities=[],
        max_visual_queries=3,
    )

    by_name = {job["entity_name"]: job for job in jobs}

    haaland = by_name["Erling Haaland"]
    assert haaland["entity_type"] == "person"
    assert haaland["usage"] == "identity"
    assert haaland["strict_identity"] is True
    assert (
        haaland["query"]
        == "Erling Haaland official profile portrait clear face single person"
    )

    idol_producer = by_name["Idol Producer"]
    assert idol_producer["entity_type"] == "ip"
    assert idol_producer["usage"] == "context"
    assert idol_producer["strict_identity"] is False
    assert (
        idol_producer["query"]
        == "Idol Producer official poster stage visual style"
    )


def test_explicit_strict_identity_false_is_preserved_in_visual_jobs():
    entities = grounding_visual_jobs._enrich_visual_entity_contract(
        [
            {
                "text": "Erling Haaland",
                "canonical": "Erling Haaland",
                "type": "person",
                "strict_identity": False,
            },
        ],
        include_visuals=True,
    )

    jobs = web_grounding._expand_visual_query_jobs(
        ["Erling Haaland official portrait"],
        context=None,
        entities=entities,
        max_visual_queries=1,
    )

    assert entities[0]["needs_visual_grounding"] is True
    assert entities[0]["strict_identity"] is False
    assert jobs[0]["usage"] == "identity"
    assert jobs[0]["strict_identity"] is False


def test_visual_jobs_infer_identity_from_string_entity_query_hints():
    jobs = web_grounding._expand_visual_query_jobs(
        [
            "Erling Haaland casual unstyled look",
            "Erling Haaland fashion idol styled look",
            "Erling Haaland personality traits real",
        ],
        context={"entities": ["Erling Haaland", "Idol Producer"]},
        entities=[],
        max_visual_queries=3,
    )

    by_name = {job["entity_name"]: job for job in jobs}

    haaland = by_name["Erling Haaland"]
    assert haaland["entity_type"] == "person"
    assert haaland["usage"] == "identity"
    assert haaland["strict_identity"] is True
    assert (
        haaland["query"]
        == "Erling Haaland official profile portrait clear face single person"
    )

    idol_producer = by_name["Idol Producer"]
    assert idol_producer["entity_type"] == "ip"
    assert idol_producer["usage"] == "context"
    assert idol_producer["strict_identity"] is False
    assert (
        idol_producer["query"]
        == "Idol Producer official poster stage visual style"
    )


def test_visual_jobs_recover_named_person_from_queries_when_entities_are_empty():
    jobs = web_grounding._expand_visual_query_jobs(
        [
            "Taylor Swift appearance facial features",
            "Taylor Swift funny moments off pitch",
            "award show stage visual style",
        ],
        context=None,
        entities=[],
        max_visual_queries=3,
    )

    identity = jobs[0]
    assert identity["entity_name"] == "Taylor Swift"
    assert identity["entity_type"] == "person"
    assert identity["usage"] == "identity"
    assert identity["strict_identity"] is True
    assert (
        identity["query"]
        == "Taylor Swift official profile portrait clear face single person"
    )
    assert jobs[1]["query"] == "award show stage visual style"
    assert jobs[1]["usage"] == "context"


def test_visual_jobs_recover_two_people_and_keep_stage_as_context():
    jobs = web_grounding._expand_visual_query_jobs(
        [
            "Erling Haaland appearance style personality",
            "Rodrigo De Paul footballer look persona",
            "Idol practice show stage visuals",
        ],
        context=None,
        entities=[],
        max_visual_queries=3,
    )

    by_name = {job["entity_name"]: job for job in jobs if job["entity_name"]}
    assert set(by_name) == {"Erling Haaland", "Rodrigo De Paul"}
    for identity in by_name.values():
        assert identity["entity_type"] == "person"
        assert identity["usage"] == "identity"
        assert identity["strict_identity"] is True
        assert identity["query"].endswith(
            "official profile portrait clear face single person",
        )

    context_jobs = [job for job in jobs if not job["entity_name"]]
    assert [job["query"] for job in context_jobs] == [
        "Idol practice show stage visuals",
    ]


def test_visual_jobs_replace_stale_fashion_person_queries_with_identity_queries():
    jobs = web_grounding._expand_visual_query_jobs(
        [
            "Erling Haaland appearance style fashion 2024",
            "Rodrigo De Paul appearance style fashion 2024",
            "idol survival show stage performance visual style",
        ],
        context=None,
        entities=[],
        max_visual_queries=3,
    )

    queries = {
        job["entity_name"]: job["query"] for job in jobs if job["entity_name"]
    }
    assert queries == {
        "Erling Haaland": "Erling Haaland official profile portrait clear face single person",
        "Rodrigo De Paul": "Rodrigo De Paul official profile portrait clear face single person",
    }
    assert all(
        "2024" not in query and "fashion" not in query
        for query in queries.values()
    )

    context_jobs = [job for job in jobs if not job["entity_name"]]
    assert [job["query"] for job in context_jobs] == [
        "idol survival show stage performance visual style",
    ]


def test_visual_jobs_support_six_unique_identity_targets_without_padding():
    names = [
        "Erling Haaland",
        "Rodrigo De Paul",
        "Lionel Messi",
        "Kylian Mbappe",
        "Jude Bellingham",
        "Vinicius Junior",
    ]
    jobs = web_grounding._expand_visual_query_jobs(
        [f"{name} footballer portrait" for name in names],
        context=None,
        entities=[],
        max_visual_queries=6,
    )

    assert {job["entity_name"] for job in jobs} == set(names)
    assert len(jobs) == 6
    assert all(job["strict_identity"] for job in jobs)


def test_visual_verification_failure_marks_every_candidate_unusable(
    monkeypatch,
):
    monkeypatch.setattr(
        verification.model_config,
        "get_vlm_api_key",
        lambda: "key",
    )

    async def fail_vlm(*args, **kwargs):
        raise RuntimeError("bad image")

    monkeypatch.setattr(verification.vlm_model, "chat_completion", fail_vlm)
    sources = [
        {
            "index": 1,
            "local_url": "file:///tmp/reference.jpg",
            "vlm_image_url": "file:///tmp/reference.jpg",
        },
    ]
    monkeypatch.setattr(
        verification,
        "multimodal_media_part",
        lambda url, media_type: {
            "type": "image_url",
            "image_url": {"url": url},
        },
    )

    verified, trace = asyncio.run(
        verification.verify_visual_grounding_with_vlm(
            "fictional athlete",
            sources,
        ),
    )

    assert trace["status"] == "degraded"
    assert verified[0]["verification"]["status"] == "error"
    assert verified[0]["verification"]["reason"].endswith(
        "RuntimeError: bad image",
    )
    assert verification._is_accepted_visual_source(verified[0]) is False


def test_visual_verification_uses_explicit_zero_timeout_consistently(
    monkeypatch,
):
    captured = {}
    monkeypatch.setattr(
        verification.model_config,
        "get_vlm_api_key",
        lambda: "key",
    )
    monkeypatch.setattr(
        verification,
        "multimodal_media_part",
        lambda url, media_type: {
            "type": "image_url",
            "image_url": {"url": url},
        },
    )

    async def fake_chat_completion(*args, **kwargs):
        captured["inner_timeout"] = kwargs["timeout"]
        return json.dumps({"selected": [], "rejected": [], "summary": ""})

    async def fake_wait_for(awaitable, timeout):
        captured["outer_timeout"] = timeout
        return await awaitable

    monkeypatch.setattr(
        verification.vlm_model,
        "chat_completion",
        fake_chat_completion,
    )
    monkeypatch.setattr(verification.asyncio, "wait_for", fake_wait_for)

    _sources, trace = asyncio.run(
        verification.verify_visual_grounding_with_vlm(
            "fictional athlete",
            [
                {
                    "index": 1,
                    "local_url": "file:///tmp/reference.jpg",
                    "vlm_image_url": "file:///tmp/reference.jpg",
                },
            ],
            timeout=0,
        ),
    )

    assert trace["status"] == "success"
    assert captured == {"inner_timeout": 0, "outer_timeout": 0}


def test_query_coverage_skips_duplicate_before_selecting_valid_candidate():
    sources = [
        {"query": "Haaland portrait", "url": "https://img.test/shared.jpg"},
        {"query": "Haaland celebration", "url": "https://img.test/shared.jpg"},
        {
            "query": "Haaland celebration",
            "url": "https://img.test/celebration.jpg",
        },
    ]

    selected = provider_search._dedupe_visual_sources_with_query_coverage(
        sources,
        query_order=["Haaland portrait", "Haaland celebration"],
        max_sources=2,
    )

    assert [source["url"] for source in selected] == [
        "https://img.test/shared.jpg",
        "https://img.test/celebration.jpg",
    ]


def test_ground_prompt_context_does_not_report_tavily_when_only_dashscope_attempted(
    monkeypatch,
):
    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": ["tavily_api_key_missing"],
            "sources": [],
            "provider": "tavily",
        }

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": ["dashscope_web_search_image:ReadTimeout: "],
            "visual_sources": [],
            "provider": "",
            "providers": [],
            "providers_attempted": ["dashscope_web_search_image"],
        }

    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        fake_search_visual_refs,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "哈兰德参加偶像练习生",
            queries=["Erling Haaland facial features"],
            force=True,
            include_visuals=True,
        ),
    )

    assert result["status"] == "degraded"
    assert result["provider"] == ""
    assert result["providers"] == []
    assert result["visual_providers_attempted"] == [
        "dashscope_web_search_image",
    ]
    assert "tavily_api_key_missing" in result["issues"]
    assert "dashscope_web_search_image:ReadTimeout: " in result["issues"]


def test_ground_prompt_context_runs_query_searches_concurrently(monkeypatch):
    queries = ["query one", "query two", "query three"]

    async def run():
        text_started = []
        visual_started = []
        all_started = asyncio.Event()

        def mark_started():
            if len(text_started) == len(queries) and len(
                visual_started,
            ) == len(queries):
                all_started.set()

        async def fake_search_web(query, *, max_sources=6, timeout=8.0):
            text_started.append(query)
            mark_started()
            await asyncio.wait_for(all_started.wait(), timeout=0.5)
            return {
                "query": query,
                "issues": [],
                "sources": [],
                "provider": "",
            }

        async def fake_search_visual_refs(
            query,
            *,
            max_sources=6,
            timeout=8.0,
        ):
            visual_started.append(query)
            mark_started()
            await asyncio.wait_for(all_started.wait(), timeout=0.5)
            return {
                "query": query,
                "issues": [],
                "visual_sources": [],
                "provider": "",
                "providers": [],
                "providers_attempted": ["fake"],
            }

        monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
        monkeypatch.setattr(
            web_grounding,
            "search_visual_refs",
            fake_search_visual_refs,
        )

        result = await asyncio.wait_for(
            web_grounding.ground_prompt_context(
                "force visual grounding",
                queries=queries,
                force=True,
                include_visuals=True,
                verify_visuals=False,
            ),
            timeout=1.0,
        )

        assert set(text_started) == set(queries)
        assert set(visual_started) == set(queries)
        assert result["visual_providers_attempted"] == ["fake"]

    asyncio.run(run())


def test_ground_prompt_context_expands_visual_entity_queries_and_preserves_coverage(
    monkeypatch,
):
    visual_calls: list[str] = []

    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "sources": [],
            "provider": "",
        }

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        visual_calls.append(query)
        slug = query.lower().replace(" ", "-")
        return {
            "query": query,
            "issues": [],
            "visual_sources": [
                {
                    "url": f"https://img.test/{slug}.jpg",
                    "title": f"{query} result",
                    "provider": "dashscope_web_search_image",
                    "query": query,
                },
            ],
            "provider": "dashscope_web_search_image",
            "providers": ["dashscope_web_search_image"],
            "providers_attempted": ["dashscope_web_search_image"],
        }

    async def fake_stage_visual_grounding_sources(
        visual_sources,
        *,
        timeout=8.0,
    ):
        return visual_sources, {
            "status": "success",
            "downloaded_count": len(visual_sources),
            "failed_count": 0,
        }

    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        fake_search_visual_refs,
    )
    monkeypatch.setattr(
        web_grounding,
        "stage_visual_grounding_sources",
        fake_stage_visual_grounding_sources,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "哈兰德参加偶像练习生",
            queries=[
                "Erling Haaland current appearance and style",
                "Idol Producer Chinese show stage visual and uniforms",
                "偶像练习生 节目 舞台 视觉 服装",
            ],
            context={
                "entities": ["Erling Haaland", "Idol Producer"],
                "base_profile": {
                    "Erling Haaland": "Norwegian professional footballer, tall blonde, athletic build",
                    "Idol Producer": "Chinese reality talent show, idol trainee competition format",
                },
            },
            force=True,
            include_visuals=True,
            verify_visuals=False,
            max_sources=4,
        ),
    )

    assert (
        "Erling Haaland official profile portrait clear face single person"
        in result["visual_queries"]
    )
    assert (
        "Idol Producer official poster stage visual style"
        in result["visual_queries"]
    )
    assert (
        "Erling Haaland official profile portrait clear face single person"
        in visual_calls
    )
    assert "Idol Producer official poster stage visual style" in visual_calls
    selected_queries = {source["query"] for source in result["visual_sources"]}
    assert (
        "Erling Haaland official profile portrait clear face single person"
        in selected_queries
    )
    assert (
        "Idol Producer official poster stage visual style" in selected_queries
    )
    assert result["visual_search_trace"][0]["source_count"] == 1


def test_ground_prompt_context_exposes_authoritative_normalized_query_plan(
    monkeypatch,
):
    text_calls = []
    visual_calls = []

    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        text_calls.append(query)
        return {"query": query, "issues": [], "sources": [], "provider": ""}

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        visual_calls.append(query)
        return {
            "query": query,
            "issues": [],
            "visual_sources": [],
            "provider": "",
            "providers": [],
            "providers_attempted": [],
        }

    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        fake_search_visual_refs,
    )

    suggested = [
        "Erling Haaland appearance personality look 2024",
        "Rodrigo De Paul appearance personality footballer 2024",
        "idol training show Chinese variety show stage performance",
    ]
    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "哈兰德参加偶像练习生，决赛对手德保罗。",
            queries=suggested,
            force=True,
            include_visuals=True,
            verify_visuals=False,
        ),
    )

    assert result["suggested_queries"] == suggested
    assert result["queries"] == [
        "Erling Haaland official profile biography",
        "Rodrigo De Paul official profile biography",
        "idol training show Chinese variety show stage performance",
    ]
    assert result["visual_queries"] == [
        "Erling Haaland official profile portrait clear face single person",
        "Rodrigo De Paul official profile portrait clear face single person",
        "idol training show Chinese variety show stage performance",
    ]
    assert result["query_plan"] == {
        "text": result["queries"],
        "visual": result["visual_queries"],
    }
    assert text_calls == result["queries"]
    assert visual_calls == result["visual_queries"]


def test_ground_prompt_context_can_verify_visual_sources_with_vlm(
    monkeypatch,
    tmp_path,
):
    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "sources": [
                {
                    "title": "Erling Haaland",
                    "url": "https://example.test/haaland",
                    "snippet": "Norway striker for Manchester City.",
                    "provider": "fake",
                    "query": query,
                },
            ],
        }

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "visual_sources": [
                {
                    "index": 1,
                    "url": "https://img.test/haaland-good.jpg",
                    "title": "Haaland portrait",
                    "query": query,
                },
                {
                    "index": 2,
                    "url": "https://img.test/wrong.jpg",
                    "title": "Wrong player",
                    "query": query,
                },
            ],
        }

    async def fake_download_visual_source(client, source, *, max_bytes):
        return {
            "payload": b"\x89PNG\r\n\x1a\nfake-image-bytes",
            "media_type": "image/png",
            "final_url": source["url"],
            "byte_size": 24,
        }

    async def fake_vlm_chat(content, **kwargs):
        image_urls = [
            part["image_url"]["url"]
            for part in content
            if isinstance(part, dict) and part.get("type") == "image_url"
        ]
        assert image_urls
        # Staged screenshots keep their local URLs at build time; the real
        # chat_completion transports them through the provider-bound channel.
        assert all(url.startswith("file://") for url in image_urls)
        return '{"selected":[{"index":1,"fit_score":0.92,"usage":"identity","reason":"clear match"}],"rejected":[{"index":2,"reason":"wrong player"}],"summary":"selected one visual ref"}'

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        fake_search_visual_refs,
    )
    monkeypatch.setattr(
        staging,
        "download_visual_source",
        fake_download_visual_source,
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_vlm_api_key",
        lambda: "key",
    )
    monkeypatch.setattr(
        verification.vlm_model,
        "chat_completion",
        fake_vlm_chat,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "make a grounded Haaland identity edit",
            queries=["Erling Haaland profile"],
            include_visuals=True,
        ),
    )

    assert result["status"] == "success"
    assert result["visual_download"]["status"] == "success"
    assert result["visual_download"]["downloaded_count"] == 2
    assert result["visual_verification"]["status"] == "success"
    assert (
        result["visual_sources"][0]["url"]
        == "https://img.test/haaland-good.jpg"
    )
    assert result["visual_sources"][0]["local_url"].startswith("file://")
    assert result["visual_sources"][0]["storage_sha256"]
    assert result["visual_sources"][0]["verification"]["status"] == "accepted"
    assert result["visual_sources"][0]["verification"]["fit_score"] == 0.92


def test_visual_grounding_ranks_per_entity_and_filters_bad_person_identity_refs(
    monkeypatch,
    tmp_path,
):
    visual_calls: list[tuple[str, int]] = []
    vlm_calls: list[list[dict]] = []

    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "sources": [],
            "provider": "",
        }

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        visual_calls.append((query, max_sources))
        if "Haaland" in query and "portrait" in query:
            sources = [
                {
                    "url": "https://ih1.redbubble.net/image/fan-art.jpg",
                    "title": "Smug Erling Haaland face Postcard for Sale by RoryPaints | Redbubble",
                    "query": query,
                    "provider": "dashscope_web_search_image",
                },
                {
                    "url": "https://media.gettyimages.com/id/haaland-photo.jpg",
                    "title": "Erling Haaland official photo portrait",
                    "query": query,
                    "provider": "dashscope_web_search_image",
                },
                {
                    "url": "https://media.gettyimages.com/id/wrong-player.jpg",
                    "title": "Norway footballer portrait",
                    "query": query,
                    "provider": "dashscope_web_search_image",
                },
            ]
        elif "Idol Producer" in query:
            sources = [
                {
                    "url": "https://play-lh.googleusercontent.com/kpop-game.webp",
                    "title": "KPop Idol Queens Production - Apps on Google Play",
                    "query": query,
                    "provider": "dashscope_web_search_image",
                },
                {
                    "url": "https://img.test/idol-producer-official-poster.jpg",
                    "title": "Idol Producer official poster stage visual style",
                    "query": query,
                    "provider": "dashscope_web_search_image",
                },
            ]
        else:
            sources = []
        return {
            "query": query,
            "issues": [],
            "visual_sources": sources[:max_sources],
            "provider": "dashscope_web_search_image",
            "providers": ["dashscope_web_search_image"] if sources else [],
            "providers_attempted": ["dashscope_web_search_image"],
        }

    async def fake_download_visual_source(client, source, *, max_bytes):
        return {
            "payload": b"\x89PNG\r\n\x1a\nfake-image-bytes",
            "media_type": "image/png",
            "final_url": source["url"],
            "byte_size": 24,
        }

    async def fake_vlm_chat(content, **kwargs):
        text = next(
            part["text"]
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
        marker = "Candidate metadata: "
        metadata_text = text.split(marker, 1)[1].split(
            "\nReturn strict JSON",
            1,
        )[0]
        metadata = json.loads(metadata_text)
        vlm_calls.append(metadata)
        titles = [item["title"] for item in metadata]
        if any(
            item.get("entity_name") == "Erling Haaland" for item in metadata
        ):
            assert all("Redbubble" not in title for title in titles)
            selected_index = next(
                item["index"]
                for item in metadata
                if item["title"] == "Erling Haaland official photo portrait"
            )
            rejected = [
                {"index": item["index"], "reason": "not the target person"}
                for item in metadata
                if item["index"] != selected_index
            ]
            return json.dumps(
                {
                    "selected": [
                        {
                            "index": selected_index,
                            "fit_score": 0.96,
                            "usage": "identity",
                            "reason": "real photographic likeness",
                        },
                    ],
                    "rejected": rejected,
                    "summary": "selected Haaland photo",
                },
            )
        selected_index = next(
            item["index"]
            for item in metadata
            if item["title"]
            == "Idol Producer official poster stage visual style"
        )
        rejected = [
            {"index": item["index"], "reason": "generic app art"}
            for item in metadata
            if item["index"] != selected_index
        ]
        return json.dumps(
            {
                "selected": [
                    {
                        "index": selected_index,
                        "fit_score": 0.91,
                        "usage": "context",
                        "reason": "official show context",
                    },
                ],
                "rejected": rejected,
                "summary": "selected Idol Producer context",
            },
        )

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        fake_search_visual_refs,
    )
    monkeypatch.setattr(
        staging,
        "download_visual_source",
        fake_download_visual_source,
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_vlm_api_key",
        lambda: "key",
    )
    monkeypatch.setattr(
        verification.vlm_model,
        "chat_completion",
        fake_vlm_chat,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "哈兰德进入偶像练习生节目；一开始毛糙，后来经过打磨和形象设计，变成万人迷",
            queries=[
                "Erling Haaland physical appearance features",
                "Idol Producer Produce 101 visual style stage design",
            ],
            context={
                "entities": [
                    {
                        "text": "哈兰德",
                        "type": "person",
                        "canonical": "Erling Haaland",
                    },
                    {
                        "text": "偶像练习生",
                        "type": "ip",
                        "canonical": "Idol Producer",
                    },
                ],
                "base_profile": {
                    "Erling Haaland": "Norwegian professional footballer, tall blonde, athletic build",
                    "Idol Producer": "Chinese reality talent show, idol trainee competition format",
                },
            },
            force=True,
            include_visuals=True,
        ),
    )

    assert {query for query, _ in visual_calls} == {
        "Erling Haaland official profile portrait clear face single person",
        "Idol Producer official poster stage visual style",
    }
    assert all(max_sources == 3 for _, max_sources in visual_calls)
    assert len(vlm_calls) == 2
    accepted = [
        source
        for source in result["visual_sources"]
        if source["verification"]["status"] == "accepted"
    ]
    assert [source["title"] for source in accepted] == [
        "Erling Haaland official photo portrait",
        "Idol Producer official poster stage visual style",
    ]
    assert "Redbubble" not in json.dumps(
        result["visual_sources"],
        ensure_ascii=False,
    )
    assert result["visual_verification"]["selected_count"] == 2
    assert [
        group["entity_name"]
        for group in result["visual_verification"]["groups"]
    ] == [
        "Erling Haaland",
        "Idol Producer",
    ]
    assert result["visual_search_trace"][0]["filtered_count"] == 1


def test_strict_identity_rejects_correct_person_when_generation_reference_quality_is_low():
    sources = [
        {
            "index": 1,
            "verification": {
                "status": "accepted",
                "fit_score": 0.96,
                "identity_score": 0.98,
                "reference_quality_score": 0.35,
                "quality_flags": [
                    "multiple_people",
                    "action_pose",
                    "small_face",
                ],
                "usage": "identity",
                "reason": "Correct athlete, but airborne in a two-player action shot.",
            },
        },
        {
            "index": 2,
            "verification": {
                "status": "accepted",
                "fit_score": 0.90,
                "identity_score": 0.94,
                "reference_quality_score": 0.88,
                "quality_flags": [
                    "single_subject",
                    "clear_face",
                    "neutral_pose",
                ],
                "usage": "identity",
                "reason": "Clear single-person portrait.",
            },
        },
    ]

    ranked = web_grounding._enforce_single_selected_visual_source(
        sources,
        job={"strict_identity": True, "usage": "identity"},
    )

    assert ranked[0]["index"] == 2
    assert ranked[0]["verification"]["status"] == "accepted"
    assert ranked[1]["index"] == 1
    assert ranked[1]["verification"]["status"] == "rejected"
    assert (
        "not suitable as a primary generation reference"
        in ranked[1]["verification"]["reason"]
    )


def test_strict_identity_visual_grounding_retries_until_photo_is_accepted(
    monkeypatch,
    tmp_path,
):
    visual_calls: list[str] = []

    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "sources": [],
            "provider": "",
        }

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        visual_calls.append(query)
        if (
            query
            == "Erling Haaland official profile portrait clear face single person"
        ):
            sources = [
                {
                    "url": "https://img.test/haaland-sketch.jpg",
                    "title": "Erling Haaland pencil drawing",
                    "query": query,
                    "provider": "dashscope_web_search_image",
                },
            ]
        elif query == "Erling Haaland official player profile portrait":
            sources = [
                {
                    "url": "https://media.gettyimages.com/id/haaland-real-photo.jpg",
                    "title": "Erling Haaland official portrait photo",
                    "query": query,
                    "provider": "dashscope_web_search_image",
                },
            ]
        else:
            sources = []
        return {
            "query": query,
            "issues": [],
            "visual_sources": sources,
            "provider": "dashscope_web_search_image" if sources else "",
            "providers": ["dashscope_web_search_image"] if sources else [],
            "providers_attempted": ["dashscope_web_search_image"],
        }

    async def fake_download_visual_source(client, source, *, max_bytes):
        return {
            "payload": b"\x89PNG\r\n\x1a\nfake-image-bytes",
            "media_type": "image/png",
            "final_url": source["url"],
            "byte_size": 24,
        }

    async def fake_vlm_chat(content, **kwargs):
        text = next(
            part["text"]
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
        metadata = json.loads(
            text.split("Candidate metadata: ", 1)[1].split(
                "\nReturn strict JSON",
                1,
            )[0],
        )
        real_photo = next(
            (
                item
                for item in metadata
                if item["title"] == "Erling Haaland official portrait photo"
            ),
            None,
        )
        if real_photo:
            return json.dumps(
                {
                    "selected": [
                        {
                            "index": real_photo["index"],
                            "fit_score": 0.97,
                            "usage": "identity",
                            "reason": "real photographic likeness",
                        },
                    ],
                    "rejected": [],
                    "summary": "accepted retry photo",
                },
            )
        return json.dumps(
            {
                "selected": [],
                "rejected": [
                    {"index": item["index"], "reason": "not a real photo"}
                    for item in metadata
                ],
                "summary": "no accepted photo",
            },
        )

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        fake_search_visual_refs,
    )
    monkeypatch.setattr(
        staging,
        "download_visual_source",
        fake_download_visual_source,
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_vlm_api_key",
        lambda: "key",
    )
    monkeypatch.setattr(
        verification.vlm_model,
        "chat_completion",
        fake_vlm_chat,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "哈兰德参加偶像练习生",
            queries=["Erling Haaland physical appearance features"],
            context={
                "entities": [
                    {
                        "text": "哈兰德",
                        "type": "person",
                        "canonical": "Erling Haaland",
                    },
                ],
            },
            force=True,
            include_visuals=True,
        ),
    )

    assert result["status"] == "success"
    assert "Erling Haaland official player profile portrait" in visual_calls
    assert (
        result["visual_sources"][0]["url"]
        == "https://media.gettyimages.com/id/haaland-real-photo.jpg"
    )
    assert result["visual_sources"][0]["verification"]["status"] == "accepted"
    assert (
        result["visual_verification"]["strict_identity_retry"]["status"]
        == "success"
    )
    assert not any(
        issue.startswith("strict_identity_reference_missing")
        for issue in result["issues"]
    )


def test_strict_identity_visual_grounding_degrades_when_no_photo_is_accepted(
    monkeypatch,
    tmp_path,
):
    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "sources": [],
            "provider": "",
        }

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "visual_sources": [
                {
                    "url": f"https://img.test/{query.lower().replace(' ', '-')}.jpg",
                    "title": "Erling Haaland fan illustration",
                    "query": query,
                    "provider": "dashscope_web_search_image",
                },
            ],
            "provider": "dashscope_web_search_image",
            "providers": ["dashscope_web_search_image"],
            "providers_attempted": ["dashscope_web_search_image"],
        }

    async def fake_download_visual_source(client, source, *, max_bytes):
        return {
            "payload": b"\x89PNG\r\n\x1a\nfake-image-bytes",
            "media_type": "image/png",
            "final_url": source["url"],
            "byte_size": 24,
        }

    async def fake_vlm_chat(content, **kwargs):
        text = next(
            part["text"]
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
        metadata = json.loads(
            text.split("Candidate metadata: ", 1)[1].split(
                "\nReturn strict JSON",
                1,
            )[0],
        )
        return json.dumps(
            {
                "selected": [],
                "rejected": [
                    {
                        "index": item["index"],
                        "reason": "illustration, not photo",
                    }
                    for item in metadata
                ],
                "summary": "no accepted strict identity photo",
            },
        )

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        fake_search_visual_refs,
    )
    monkeypatch.setattr(
        staging,
        "download_visual_source",
        fake_download_visual_source,
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_vlm_api_key",
        lambda: "key",
    )
    monkeypatch.setattr(
        verification.vlm_model,
        "chat_completion",
        fake_vlm_chat,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "哈兰德参加偶像练习生",
            queries=["Erling Haaland physical appearance features"],
            context={
                "entities": [
                    {
                        "text": "哈兰德",
                        "type": "person",
                        "canonical": "Erling Haaland",
                    },
                ],
            },
            force=True,
            include_visuals=True,
        ),
    )

    assert result["status"] == "degraded"
    assert (
        result["visual_verification"]["strict_identity_retry"]["status"]
        == "degraded"
    )
    assert (
        "strict_identity_reference_missing:Erling Haaland" in result["issues"]
    )


def test_ground_prompt_context_renders_visual_refs_in_grounded_context(
    monkeypatch,
    tmp_path,
):
    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "sources": [
                {
                    "title": "Yi silver ornament reference",
                    "url": "https://example.test/yi-silver",
                    "snippet": "Yi ethnic silver ornaments and traditional costume details.",
                    "provider": "fake",
                    "query": query,
                },
            ],
        }

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "visual_sources": [
                {
                    "url": "https://img.test/yi-silver.jpg",
                    "source_url": "https://example.test/yi-silver",
                    "title": "Yi silver headdress reference",
                    "query": query,
                },
            ],
        }

    async def fake_download_visual_source(client, source, *, max_bytes):
        return {
            "payload": b"\x89PNG\r\n\x1a\nfake-yi-silver-image",
            "media_type": "image/png",
            "final_url": source["url"],
            "byte_size": 28,
        }

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        fake_search_visual_refs,
    )
    monkeypatch.setattr(
        staging,
        "download_visual_source",
        fake_download_visual_source,
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_vlm_api_key",
        lambda: "",
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "彝族银饰视觉参考",
            queries=["彝族银饰 传统服饰 视觉参考"],
            include_visuals=True,
        ),
    )

    assert result["status"] == "success"
    assert result["visual_download"]["status"] == "success"
    assert (
        result["visual_sources"][0]["url"] == "https://img.test/yi-silver.jpg"
    )
    assert result["visual_sources"][0]["local_url"].startswith("file://")
    assert "Visual References:" in result["grounded_context"]
    assert "https://img.test/yi-silver.jpg" in result["grounded_context"]
    assert "local=file://" in result["grounded_context"]
    assert "Yi silver headdress reference" in result["grounded_context"]


def test_search_web_uses_tavily_when_keyed(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    async def fake_tavily(client, query, limit):
        return [
            {
                "title": "Tavily result",
                "url": "https://example.test/tavily",
                "snippet": "source-backed content",
                "provider": "tavily",
                "query": query,
            },
        ]

    monkeypatch.setattr(provider_search, "_search_tavily", fake_tavily)

    result = asyncio.run(web_grounding.search_web("Erling Haaland"))

    assert result["provider"] == "tavily"
    assert result["sources"][0]["provider"] == "tavily"
    assert result["issues"] == []


def test_search_web_reports_when_both_provider_keys_are_missing(monkeypatch):
    monkeypatch.setattr(provider_search, "_tavily_api_key", lambda: "")
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: "",
    )

    result = asyncio.run(web_grounding.search_web("Erling Haaland"))

    assert result["provider"] == ""
    assert result["sources"] == []
    assert result["issues"] == [
        "tavily_api_key_missing",
        "dashscope_web_search_api_key_missing",
    ]


def test_public_provider_helpers_are_removed():
    assert not hasattr(web_grounding, "_search_duckduckgo")
    assert not hasattr(web_grounding, "_search_wikidata")
    assert not hasattr(web_grounding, "_search_wikipedia")

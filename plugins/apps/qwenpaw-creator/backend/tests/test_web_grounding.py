# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,protected-access,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
import asyncio
import io
import json

import httpx
import pytest
import respx
from PIL import Image

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


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_dashscope_model_falls_back_when_model_config_raises(monkeypatch):
    def fail_model_name():
        raise RuntimeError("model config is not initialized")

    monkeypatch.setattr(
        provider_config.model_config,
        "get_web_grounding_search_model_name",
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
    result = web_grounding.detect_grounding_needs(
        "编一个虚构太空厨师的短片 prompt，风格温暖",
    )

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

    triage = asyncio.run(
        web_grounding.triage_grounding_request("剪辑哈兰德的国家队高光"),
    )

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


def test_search_serper_maps_response(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    monkeypatch.delenv("SERPER_SEARCH_URL", raising=False)
    payload = {
        "organic": [
            {
                "title": "Erling Haaland Facts",
                "link": "https://example.test/haaland",
                "snippet": "Norway striker for Manchester City.",
                "position": 1,
            },
            {"snippet": "missing title and link"},
        ],
    }

    async def run():
        async with httpx.AsyncClient() as client:
            return await adapters._search_serper(
                client,
                "Erling Haaland",
                3,
            )

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://google.serper.dev/search").mock(
            return_value=httpx.Response(200, json=payload),
        )
        results = asyncio.run(run())

    request = route.calls.last.request
    assert request.headers["X-API-KEY"] == "serper-test"
    assert json.loads(request.content)["q"] == "Erling Haaland"
    assert results == [
        {
            "title": "Erling Haaland Facts",
            "url": "https://example.test/haaland",
            "snippet": "Norway striker for Manchester City.",
            "provider": "serper",
            "query": "Erling Haaland",
            "score": None,
        },
    ]


def test_search_serper_requires_api_key(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_SERPER_API_KEY", raising=False)
    client = _FakeClient({"organic": []})

    with pytest.raises(RuntimeError, match="SERPER_API_KEY"):
        asyncio.run(adapters._search_serper(client, "Erling Haaland", 3))
    assert not client.calls


def test_search_serper_visuals_maps_response(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    monkeypatch.delenv("SERPER_IMAGES_URL", raising=False)
    payload = {
        "images": [
            {
                "title": "Yi silver headdress",
                "imageUrl": "https://img.test/yi-silver.jpg",
                "thumbnailUrl": "https://img.test/yi-silver-thumb.jpg",
                "link": "https://example.test/yi",
                "source": "example.test",
            },
            {"source": "no image url"},
        ],
    }

    async def run():
        async with httpx.AsyncClient() as client:
            return await adapters._search_serper_visuals(client, "彝族银饰", 3)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://google.serper.dev/images").mock(
            return_value=httpx.Response(200, json=payload),
        )
        results = asyncio.run(run())

    request = route.calls.last.request
    assert request.headers["X-API-KEY"] == "serper-test"
    assert json.loads(request.content)["q"] == "彝族银饰"
    assert results == [
        {
            "url": "https://img.test/yi-silver.jpg",
            "thumbnail_url": "https://img.test/yi-silver-thumb.jpg",
            "source_url": "https://example.test/yi",
            "title": "Yi silver headdress",
            "provider": "serper",
            "query": "彝族银饰",
        },
    ]


def test_search_serper_retries_transient_5xx(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    calls = []

    async def no_sleep(_seconds):
        return None

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Recovered",
                        "link": "https://example.test/recovered",
                        "snippet": "retry succeeded",
                    },
                ],
            },
        )

    monkeypatch.setattr(adapters.asyncio, "sleep", no_sleep)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await adapters._search_serper(client, "retry query", 3)

    results = asyncio.run(run())

    assert len(calls) == 2
    assert results[0]["title"] == "Recovered"


def test_search_serper_classifies_auth_failure_without_retry(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(403, json={"error": "forbidden"})

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await adapters._search_serper(client, "forbidden query", 3)

    with pytest.raises(adapters.SerperAuthenticationError, match="HTTP 403"):
        asyncio.run(run())
    assert len(calls) == 1


def test_extract_serper_pages_maps_markdown_and_goal(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    observed = {}

    async def handler(request):
        observed["url"] = str(request.url)
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"title": "Eiffel Tower", "markdown": "Built in 1889."},
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await adapters._extract_serper_pages(
                client,
                ["https://example.test/eiffel"],
                goal="construction year",
            )

    results = asyncio.run(run())

    assert observed == {
        "url": "https://google.serper.dev/scrape",
        "payload": {
            "url": "https://example.test/eiffel",
            "includeMarkdown": True,
        },
    }
    assert results[0]["provider"] == "serper_scrape"
    assert results[0]["goal"] == "construction year"
    assert results[0]["content"] == "Built in 1889."


def test_extract_web_pages_keeps_other_urls_when_one_fails(monkeypatch):
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "key")
    monkeypatch.setattr(
        provider_search,
        "_validate_public_remote_url",
        lambda value: value,
    )

    async def fake_extract(client, urls, *, goal="", content_limit=8000):
        if "bad" in urls[0]:
            raise httpx.TimeoutException("timeout")
        return [
            {
                "title": "Good page",
                "url": urls[0],
                "snippet": "confirmed",
                "content": "confirmed",
                "goal": goal,
                "provider": "serper_scrape",
                "query": goal,
                "score": None,
            },
        ]

    monkeypatch.setattr(provider_search, "_extract_serper_pages", fake_extract)

    result = asyncio.run(
        provider_search.extract_web_pages(
            ["https://bad.test/page", "https://good.test/page"],
            goal="confirm identity",
        ),
    )

    assert len(result["sources"]) == 1
    assert result["sources"][0]["url"] == "https://good.test/page"
    assert result["provider"] == "serper_scrape"
    assert any("TimeoutException" in issue for issue in result["issues"])


def test_search_tavily_omits_safe_search_by_default(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.delenv("TAVILY_SAFE_SEARCH", raising=False)
    text_client = _FakeClient({"results": []})
    visual_client = _FakeClient({"images": []})

    asyncio.run(adapters._search_tavily(text_client, "Erling Haaland", 3))
    asyncio.run(
        adapters._search_tavily_visuals(visual_client, "Erling Haaland", 3),
    )

    # Tavily rejects safe_search outside enterprise plans with HTTP 403.
    assert "safe_search" not in text_client.calls[0][1]["json"]
    assert "safe_search" not in visual_client.calls[0][1]["json"]


def test_search_tavily_sends_safe_search_when_opted_in(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("TAVILY_SAFE_SEARCH", "1")
    text_client = _FakeClient({"results": []})
    visual_client = _FakeClient({"images": []})

    asyncio.run(adapters._search_tavily(text_client, "Erling Haaland", 3))
    asyncio.run(
        adapters._search_tavily_visuals(visual_client, "Erling Haaland", 3),
    )

    assert text_client.calls[0][1]["json"]["safe_search"] is True
    assert visual_client.calls[0][1]["json"]["safe_search"] is True


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
        "_serper_api_key",
        lambda: "serper-key",
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

    async def fail_serper(*args, **kwargs):
        raise AssertionError("Serper should not run when Tavily succeeds")

    async def fail_dashscope(*args, **kwargs):
        raise AssertionError("DashScope should not run when Tavily succeeds")

    monkeypatch.setattr(provider_search, "_search_tavily", fake_tavily)
    monkeypatch.setattr(provider_search, "_search_serper", fail_serper)
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
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "")
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
    assert "serper_api_key_missing" in result["issues"]


def test_search_web_prefers_serper_over_dashscope_when_tavily_empty(
    monkeypatch,
):
    monkeypatch.setattr(
        provider_search,
        "_tavily_api_key",
        lambda: "tavily-key",
    )
    monkeypatch.setattr(
        provider_search,
        "_serper_api_key",
        lambda: "serper-key",
    )
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: "dashscope-key",
    )

    async def empty_tavily(client, query, limit):
        return []

    async def fake_serper(client, query, limit):
        return [
            {
                "title": "Serper source",
                "url": "https://example.test/serper",
                "snippet": "source",
                "provider": "serper",
                "query": query,
                "score": None,
            },
        ]

    async def fail_dashscope(*args, **kwargs):
        raise AssertionError("DashScope should not run when Serper succeeds")

    monkeypatch.setattr(provider_search, "_search_tavily", empty_tavily)
    monkeypatch.setattr(provider_search, "_search_serper", fake_serper)
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web",
        fail_dashscope,
    )

    result = asyncio.run(web_grounding.search_web("Erling Haaland"))

    assert result["provider"] == "serper"
    assert result["providers"] == ["serper"]
    assert result["providers_attempted"] == ["tavily", "serper"]
    assert result["sources"][0]["url"] == "https://example.test/serper"
    assert "tavily:no_text_sources" in result["issues"]


def test_search_web_skips_serper_without_key_before_dashscope(monkeypatch):
    monkeypatch.setattr(provider_search, "_tavily_api_key", lambda: "")
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "")
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: "dashscope-key",
    )

    async def fail_serper(*args, **kwargs):
        raise AssertionError("Serper should not run without an API key")

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

    monkeypatch.setattr(provider_search, "_search_serper", fail_serper)
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web",
        fake_dashscope,
    )

    result = asyncio.run(web_grounding.search_web("Erling Haaland"))

    assert result["provider"] == "dashscope_web_search"
    assert result["providers_attempted"] == ["dashscope_web_search"]
    assert "serper_api_key_missing" in result["issues"]


def test_search_web_falls_back_to_serper_when_serper_errors_then_dashscope(
    monkeypatch,
):
    monkeypatch.setattr(provider_search, "_tavily_api_key", lambda: "")
    monkeypatch.setattr(
        provider_search,
        "_serper_api_key",
        lambda: "serper-key",
    )
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: "dashscope-key",
    )

    async def broken_serper(client, query, limit):
        raise RuntimeError("serper quota exceeded")

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

    monkeypatch.setattr(provider_search, "_search_serper", broken_serper)
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web",
        fake_dashscope,
    )

    result = asyncio.run(web_grounding.search_web("Erling Haaland"))

    assert result["provider"] == "dashscope_web_search"
    assert result["providers_attempted"] == [
        "serper",
        "dashscope_web_search",
    ]
    assert "serper:RuntimeError: serper quota exceeded" in result["issues"]
    assert "serper:no_text_sources" in result["issues"]


def test_search_web_falls_back_to_dashscope_when_tavily_empty(monkeypatch):
    monkeypatch.setattr(
        provider_search,
        "_tavily_api_key",
        lambda: "tavily-key",
    )
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "")
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
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "")
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


def test_search_visual_refs_supplements_insufficient_tavily_results(
    monkeypatch,
):
    monkeypatch.delenv("WEB_GROUNDING_IMAGE_PROVIDERS", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_VISUAL_PROVIDERS", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_SERPER_API_KEY", raising=False)
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

    async def fake_dashscope(client, query, limit):
        return [
            {
                "url": "https://img.test/qwen.jpg",
                "title": "Qwen image",
                "provider": "dashscope_web_search_image",
                "query": query,
            },
        ]

    monkeypatch.setattr(provider_search, "_search_tavily_visuals", fake_tavily)
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web_search_image_visuals",
        fake_dashscope,
    )

    result = asyncio.run(web_grounding.search_visual_refs("Erling Haaland"))

    assert result["providers"] == [
        "tavily",
        "dashscope_web_search_image",
    ]
    assert result["provider"] == "dashscope_web_search_image"
    assert [source["url"] for source in result["visual_sources"]] == [
        "https://img.test/tavily.jpg",
        "https://img.test/qwen.jpg",
    ]


def test_visual_provider_order_is_fixed_and_ignores_legacy_override(
    monkeypatch,
):
    monkeypatch.setenv(
        "WEB_GROUNDING_IMAGE_PROVIDERS",
        "dashscope_web_search_image,tavily",
    )
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_SERPER_API_KEY", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")

    assert provider_config.visual_search_provider_order() == (
        "tavily",
        "dashscope_web_search_image",
    )


def test_visual_provider_order_includes_serper_when_keyed(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")

    assert provider_config.visual_search_provider_order() == (
        "tavily",
        "serper",
        "dashscope_web_search_image",
    )


def test_search_visual_refs_uses_serper_after_insufficient_tavily_results(
    monkeypatch,
):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
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

    async def fake_serper(client, query, limit):
        return [
            {
                "url": "https://img.test/serper.jpg",
                "title": "Serper image",
                "provider": "serper",
                "query": query,
            },
        ]

    async def fail_dashscope(*args, **kwargs):
        raise AssertionError(
            "DashScope should not run once min results are met",
        )

    monkeypatch.setattr(provider_search, "_search_tavily_visuals", fake_tavily)
    monkeypatch.setattr(
        provider_search,
        "_search_serper_visuals",
        fake_serper,
    )
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web_search_image_visuals",
        fail_dashscope,
    )

    result = asyncio.run(web_grounding.search_visual_refs("Erling Haaland"))

    assert result["providers"] == ["tavily", "serper"]
    assert result["providers_attempted"] == ["tavily", "serper"]
    assert [source["url"] for source in result["visual_sources"]] == [
        "https://img.test/tavily.jpg",
        "https://img.test/serper.jpg",
    ]


def test_search_visual_refs_reports_serper_error_and_falls_back(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")

    async def broken_serper(client, query, limit):
        raise RuntimeError("serper quota exceeded")

    async def fake_dashscope(client, query, limit):
        return [
            {
                "url": "https://img.test/qwen.jpg",
                "title": "Qwen image",
                "provider": "dashscope_web_search_image",
                "query": query,
            },
        ]

    monkeypatch.setattr(
        provider_search,
        "_search_serper_visuals",
        broken_serper,
    )
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web_search_image_visuals",
        fake_dashscope,
    )

    result = asyncio.run(web_grounding.search_visual_refs("彝族银饰"))

    assert result["providers"] == ["dashscope_web_search_image"]
    assert result["providers_attempted"] == [
        "serper",
        "dashscope_web_search_image",
    ]
    assert (
        "serper_images:RuntimeError: serper quota exceeded" in result["issues"]
    )


def test_search_visual_refs_falls_back_to_dashscope_when_tavily_empty(
    monkeypatch,
):
    monkeypatch.delenv("WEB_GROUNDING_IMAGE_PROVIDERS", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_VISUAL_PROVIDERS", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_SERPER_API_KEY", raising=False)
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
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_SERPER_API_KEY", raising=False)
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
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_SERPER_API_KEY", raising=False)
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
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_SERPER_API_KEY", raising=False)
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
        "get_web_grounding_model_api_key",
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
        "get_web_grounding_model_api_key",
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


def test_visual_verification_retries_timeout_with_bounded_backoff(
    monkeypatch,
):
    calls: list[float] = []
    monkeypatch.setattr(
        verification.model_config,
        "get_web_grounding_model_api_key",
        lambda: "key",
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_web_grounding_verification_max_attempts",
        lambda: 3,
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_web_grounding_verification_total_budget_seconds",
        lambda: 300,
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_web_grounding_retry_base_seconds",
        lambda: 1,
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_web_grounding_retry_max_seconds",
        lambda: 8,
    )
    monkeypatch.setattr(verification.random, "uniform", lambda _low, _high: 0)
    monkeypatch.setattr(
        verification,
        "multimodal_media_part",
        lambda url, media_type: {
            "type": "image_url",
            "image_url": {"url": url},
        },
    )

    async def flaky_chat_completion(*args, **kwargs):
        calls.append(kwargs["timeout"])
        if len(calls) == 1:
            raise TimeoutError("provider timed out")
        return json.dumps({"selected": [], "rejected": [], "summary": ""})

    monkeypatch.setattr(
        verification.vlm_model,
        "chat_completion",
        flaky_chat_completion,
    )

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
            timeout=120,
        ),
    )

    assert trace["status"] == "success"
    assert trace["attempt_count"] == 2
    assert [item["status"] for item in trace["attempts"]] == [
        "failed",
        "success",
    ]
    assert trace["attempts"][0]["retryable"] is True
    assert calls == [120, 120]


def test_ground_prompt_context_skips_every_stage_when_disabled(monkeypatch):
    monkeypatch.setattr(
        web_grounding.model_config,
        "get_web_grounding_enabled",
        lambda: False,
    )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("grounding stage should not run")

    monkeypatch.setattr(
        web_grounding,
        "triage_grounding_request",
        fail_if_called,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "find current references",
            force=True,
            include_visuals=True,
        ),
    )

    assert result["status"] == "skipped"
    assert result["detector"] == "disabled"
    assert result["issues"] == ["grounding_disabled"]


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
        "get_web_grounding_model_api_key",
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
        "get_web_grounding_model_api_key",
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
        "get_web_grounding_model_api_key",
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
        "get_web_grounding_model_api_key",
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
        "get_web_grounding_model_api_key",
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
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "")
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
        "serper_api_key_missing",
        "dashscope_web_search_api_key_missing",
    ]


def test_search_web_skips_incompatible_native_search_model(monkeypatch):
    monkeypatch.setattr(provider_search, "_tavily_api_key", lambda: "")
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "")
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: "generic-key",
    )
    monkeypatch.setattr(
        provider_search,
        "_dashscope_native_search_unavailable_reason",
        lambda **kwargs: "native_search_provider_incompatible",
    )

    async def fail_native_search(*args, **kwargs):
        raise AssertionError("incompatible model must not receive web_search")

    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web",
        fail_native_search,
    )

    result = asyncio.run(web_grounding.search_web("Erling Haaland"))

    assert result["providers_attempted"] == []
    assert (
        "dashscope_web_search:native_search_provider_incompatible"
        in result["issues"]
    )


def test_public_provider_helpers_are_removed():
    assert not hasattr(web_grounding, "_search_duckduckgo")
    assert not hasattr(web_grounding, "_search_wikidata")
    assert not hasattr(web_grounding, "_search_wikipedia")


def test_search_serper_lens_maps_response(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    monkeypatch.delenv("SERPER_LENS_URL", raising=False)
    payload = {
        "organic": [
            {
                "title": "Erling Haaland portrait",
                "source": "example.test",
                "link": "https://example.test/haaland-photo",
                "imageUrl": "https://img.test/haaland.jpg",
                "thumbnailUrl": "https://img.test/haaland-thumb.jpg",
            },
            {"title": "missing image url"},
        ],
    }

    async def run():
        async with httpx.AsyncClient() as client:
            return await adapters._search_serper_lens(
                client,
                "https://public.test/reference.jpg",
                3,
                query="Erling Haaland",
            )

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://google.serper.dev/lens").mock(
            return_value=httpx.Response(200, json=payload),
        )
        results = asyncio.run(run())

    request = route.calls.last.request
    assert request.headers["X-API-KEY"] == "serper-test"
    assert json.loads(request.content) == {
        "url": "https://public.test/reference.jpg",
        "gl": "us",
        "hl": "en",
    }
    assert results == [
        {
            "url": "https://img.test/haaland.jpg",
            "thumbnail_url": "https://img.test/haaland-thumb.jpg",
            "source_url": "https://example.test/haaland-photo",
            "title": "Erling Haaland portrait",
            "provider": "serper_lens",
            "query": "Erling Haaland",
        },
    ]


def test_search_serper_lens_retries_transient_empty_organic(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    monkeypatch.delenv("SERPER_LENS_URL", raising=False)
    monkeypatch.setattr(
        adapters,
        "SERPER_LENS_EMPTY_RETRY_BACKOFF_SECONDS",
        0.0,
    )
    populated = {
        "organic": [
            {
                "title": "Eiffel Tower",
                "link": "https://example.test/eiffel",
                "imageUrl": "https://img.test/eiffel.jpg",
            },
        ],
    }

    async def run():
        async with httpx.AsyncClient() as client:
            return await adapters._search_serper_lens(
                client,
                "https://public.test/reference.jpg",
                3,
                query="Eiffel Tower",
            )

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://google.serper.dev/lens").mock(
            side_effect=[
                httpx.Response(200, json={"organic": []}),
                httpx.Response(200, json=populated),
            ],
        )
        results = asyncio.run(run())

    assert route.call_count == 2
    assert [source["url"] for source in results] == [
        "https://img.test/eiffel.jpg",
    ]


def test_search_serper_lens_gives_up_after_bounded_empty_retries(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    monkeypatch.delenv("SERPER_LENS_URL", raising=False)
    monkeypatch.setattr(
        adapters,
        "SERPER_LENS_EMPTY_RETRY_BACKOFF_SECONDS",
        0.0,
    )

    async def run():
        async with httpx.AsyncClient() as client:
            return await adapters._search_serper_lens(
                client,
                "https://public.test/reference.jpg",
                3,
            )

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://google.serper.dev/lens").mock(
            return_value=httpx.Response(200, json={"organic": []}),
        )
        results = asyncio.run(run())

    assert route.call_count == adapters.SERPER_LENS_EMPTY_RESULT_ATTEMPTS
    assert results == []


def test_search_visual_refs_by_image_uses_public_http_url(monkeypatch):
    monkeypatch.setattr(
        provider_search,
        "_serper_api_key",
        lambda: "serper-key",
    )
    monkeypatch.setattr(
        provider_search,
        "_validate_public_remote_url",
        lambda value: value,
    )
    captured = {}

    async def fake_lens(client, image_url, limit, *, query=""):
        captured["image_url"] = image_url
        captured["query"] = query
        return [
            {
                "url": "https://img.test/match.jpg",
                "thumbnail_url": "",
                "source_url": "https://example.test/match",
                "title": "Match",
                "provider": "serper_lens",
                "query": query,
            },
        ]

    monkeypatch.setattr(provider_search, "_search_serper_lens", fake_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            "https://public.test/reference.jpg",
            query="Erling Haaland",
        ),
    )

    assert captured["image_url"] == "https://public.test/reference.jpg"
    assert captured["query"] == "Erling Haaland"
    assert result["provider"] == "serper_lens"
    assert result["providers"] == ["serper_lens"]
    assert result["providers_attempted"] == ["serper_lens"]
    assert result["visual_sources"][0]["url"] == "https://img.test/match.jpg"
    assert result["issues"] == []


def test_search_visual_refs_by_image_requires_serper_key(monkeypatch):
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "")

    async def fail_lens(*args, **kwargs):
        raise AssertionError("Lens must not run without a Serper key")

    monkeypatch.setattr(provider_search, "_search_serper_lens", fail_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            "https://public.test/reference.jpg",
        ),
    )

    assert result["visual_sources"] == []
    assert result["providers_attempted"] == []
    assert result["issues"] == ["serper_api_key_missing"]


def test_search_visual_refs_by_image_rejects_dashscope_oss_url(monkeypatch):
    monkeypatch.setattr(
        provider_search,
        "_serper_api_key",
        lambda: "serper-key",
    )

    async def fail_lens(*args, **kwargs):
        raise AssertionError("oss:// URLs must never reach Serper Lens")

    monkeypatch.setattr(provider_search, "_search_serper_lens", fail_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            "oss://temp/reference.jpg",
        ),
    )

    assert result["visual_sources"] == []
    assert result["providers_attempted"] == []
    assert any(
        issue.startswith("serper_lens:oss_url_not_public")
        for issue in result["issues"]
    )


def test_search_visual_refs_by_image_rejects_non_public_http_url(monkeypatch):
    monkeypatch.setattr(
        provider_search,
        "_serper_api_key",
        lambda: "serper-key",
    )

    async def fail_lens(*args, **kwargs):
        raise AssertionError("private addresses must never reach Serper Lens")

    monkeypatch.setattr(provider_search, "_search_serper_lens", fail_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            "http://127.0.0.1/private.jpg",
        ),
    )

    assert result["visual_sources"] == []
    assert result["providers_attempted"] == []
    assert any(
        issue.startswith("serper_lens:non_public_image_url")
        for issue in result["issues"]
    )


def test_search_visual_refs_by_image_rejects_paths_outside_data_root(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        provider_search,
        "_serper_api_key",
        lambda: "serper-key",
    )
    data_root = tmp_path / "creator-data"
    data_root.mkdir()
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    outside_image = tmp_path / "outside.png"
    outside_image.write_bytes(_png_bytes())

    async def fail_presign(*args, **kwargs):
        raise AssertionError("files outside the data root must not upload")

    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_for_temporary_public_url",
        fail_presign,
    )

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(str(outside_image)),
    )

    assert result["visual_sources"] == []
    assert result["providers_attempted"] == []
    assert any(
        issue.startswith("serper_lens:invalid_local_image_reference")
        for issue in result["issues"]
    )


def test_search_visual_refs_by_image_rejects_non_image_local_files(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        provider_search,
        "_serper_api_key",
        lambda: "serper-key",
    )
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    secret_file = tmp_path / "model_config.json"
    secret_file.write_bytes(b'{"llm": {"api_key": "sk-secret"}}')

    async def fail_presign(*args, **kwargs):
        raise AssertionError("non-image files must not upload")

    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_for_temporary_public_url",
        fail_presign,
    )

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(str(secret_file)),
    )

    assert result["visual_sources"] == []
    assert result["providers_attempted"] == []
    assert any(
        issue.startswith("serper_lens:invalid_local_image_reference")
        for issue in result["issues"]
    )


def test_search_visual_refs_by_image_uses_uguu_without_oss_for_local_media(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        provider_search,
        "_serper_api_key",
        lambda: "serper-key",
    )
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    local_image = tmp_path / "reference.png"
    local_image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        provider_search._media_transport,
        "creator_oss_readiness",
        lambda: {
            "status": "absent",
            "blockers": [],
        },
    )
    uploaded = {}

    async def fake_uguu(file_content, filename, **kwargs):
        uploaded["content"] = file_content
        uploaded["filename"] = filename
        return "https://uguu.test/reference.png"

    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_to_uguu_for_temporary_public_url",
        fake_uguu,
    )
    monkeypatch.setattr(
        provider_search,
        "_validate_public_remote_url",
        lambda value: value,
    )

    async def fake_lens(client, image_url, limit, *, query=""):
        assert image_url == "https://uguu.test/reference.png"
        return [
            {
                "url": "https://img.test/match.jpg",
                "thumbnail_url": "",
                "source_url": "",
                "title": "Match",
                "provider": "serper_lens",
                "query": query,
            },
        ]

    monkeypatch.setattr(provider_search, "_search_serper_lens", fake_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(str(local_image)),
    )

    assert uploaded == {
        "content": _png_bytes(),
        "filename": "reference.png",
    }
    assert result["provider"] == "serper_lens"
    assert result["image_transport"] == "uguu"
    assert result["issues"] == []


def test_search_visual_refs_by_image_presigns_local_media_when_oss_ready(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        provider_search,
        "_serper_api_key",
        lambda: "serper-key",
    )
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    local_image = tmp_path / "reference.png"
    local_image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        provider_search._media_transport,
        "creator_oss_readiness",
        lambda: {"status": "ready", "blockers": []},
    )
    uploaded = {}

    async def fake_presign(file_content, filename, **kwargs):
        uploaded["content"] = file_content
        uploaded["filename"] = filename
        return "https://bucket.test/grounding_lens/reference.jpg?Signature=abc"

    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_for_temporary_public_url",
        fake_presign,
    )
    captured = {}

    async def fake_lens(client, image_url, limit, *, query=""):
        captured["image_url"] = image_url
        return [
            {
                "url": "https://img.test/match.jpg",
                "thumbnail_url": "",
                "source_url": "",
                "title": "Match",
                "provider": "serper_lens",
                "query": query,
            },
        ]

    monkeypatch.setattr(provider_search, "_search_serper_lens", fake_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            str(local_image),
            query="local reference",
        ),
    )

    assert uploaded["content"] == _png_bytes()
    assert uploaded["filename"] == "reference.png"
    assert captured["image_url"].startswith("https://bucket.test/")
    assert result["provider"] == "serper_lens"
    # The signed URL must never leak into the result payload.
    assert result["query"] == "local reference"
    assert result["image_reference"] == ""
    assert result["image_reference_kind"] == "local_media"
    assert result["image_transport"] == "creator_oss"


def test_search_visual_refs_by_image_falls_back_to_uguu_for_invalid_oss(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "key")
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    local_image = tmp_path / "reference.png"
    local_image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        provider_search._media_transport,
        "creator_oss_readiness",
        lambda: {
            "status": "invalid",
            "blockers": ["creator_media_oss.endpoint is required"],
        },
    )

    async def fake_uguu(*args, **kwargs):
        return "https://uguu.test/reference.png"

    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_to_uguu_for_temporary_public_url",
        fake_uguu,
    )
    monkeypatch.setattr(
        provider_search,
        "_validate_public_remote_url",
        lambda value: value,
    )

    async def fake_lens(client, image_url, limit, *, query=""):
        assert image_url == "https://uguu.test/reference.png"
        return []

    monkeypatch.setattr(provider_search, "_search_serper_lens", fake_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(str(local_image)),
    )

    assert result["visual_sources"] == []
    assert result["providers_attempted"] == ["serper_lens"]
    assert result["image_transport"] == "uguu"
    assert any(
        issue.startswith("serper_lens:creator_oss_invalid")
        for issue in result["issues"]
    )


def test_search_visual_refs_by_image_falls_back_to_uguu_after_oss_failure(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "key")
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    local_image = tmp_path / "reference.png"
    local_image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        provider_search._media_transport,
        "creator_oss_readiness",
        lambda: {"status": "ready", "blockers": []},
    )

    async def fail_oss(*args, **kwargs):
        raise RuntimeError("OSS unavailable")

    async def fake_uguu(*args, **kwargs):
        return "https://uguu.test/reference.png"

    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_for_temporary_public_url",
        fail_oss,
    )
    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_to_uguu_for_temporary_public_url",
        fake_uguu,
    )
    monkeypatch.setattr(
        provider_search,
        "_validate_public_remote_url",
        lambda value: value,
    )

    async def fake_lens(client, image_url, limit, *, query=""):
        assert image_url == "https://uguu.test/reference.png"
        return []

    monkeypatch.setattr(provider_search, "_search_serper_lens", fake_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(str(local_image)),
    )

    assert result["providers_attempted"] == ["serper_lens"]
    assert result["image_transport"] == "uguu"
    assert any(
        issue.startswith("serper_lens:creator_oss_upload_failed")
        for issue in result["issues"]
    )


def test_search_visual_refs_by_image_reports_both_transport_failures(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "key")
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    local_image = tmp_path / "reference.png"
    local_image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        provider_search._media_transport,
        "creator_oss_readiness",
        lambda: {"status": "ready", "blockers": []},
    )

    async def fail_oss(*args, **kwargs):
        raise RuntimeError("OSS unavailable")

    async def fail_uguu(*args, **kwargs):
        raise RuntimeError("Uguu unavailable")

    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_for_temporary_public_url",
        fail_oss,
    )
    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_to_uguu_for_temporary_public_url",
        fail_uguu,
    )

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(str(local_image)),
    )

    assert result["providers_attempted"] == []
    assert result["image_transport"] == "uguu"
    assert any(
        issue.startswith("serper_lens:creator_oss_upload_failed")
        for issue in result["issues"]
    )
    assert any(
        issue.startswith("serper_lens:uguu_upload_failed")
        for issue in result["issues"]
    )


def test_search_visual_refs_by_image_crops_bbox_before_uguu(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "key")
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    local_image = tmp_path / "reference.png"
    local_image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        provider_search._media_transport,
        "creator_oss_readiness",
        lambda: {"status": "absent", "blockers": []},
    )
    cropped = {}

    async def fake_uguu(file_content, filename, **kwargs):
        with Image.open(io.BytesIO(file_content)) as image:
            cropped["size"] = image.size
        cropped["filename"] = filename
        return "https://uguu.test/cropped.jpg"

    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_to_uguu_for_temporary_public_url",
        fake_uguu,
    )
    monkeypatch.setattr(
        provider_search,
        "_validate_public_remote_url",
        lambda value: value,
    )

    async def fake_lens(client, image_url, limit, *, query=""):
        return []

    monkeypatch.setattr(provider_search, "_search_serper_lens", fake_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            str(local_image),
            bbox=[0, 0, 500, 1000],
        ),
    )

    assert cropped == {"size": (2, 4), "filename": "reference-crop.jpg"}
    assert result["bbox"] == [0, 0, 500, 1000]
    assert result["image_transport"] == "uguu"


def test_search_visual_refs_by_image_rejects_invalid_bbox_before_upload(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: "key")
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    local_image = tmp_path / "reference.png"
    local_image.write_bytes(_png_bytes())

    async def fail_upload(*args, **kwargs):
        raise AssertionError("invalid bbox must not upload")

    monkeypatch.setattr(
        provider_search._media_transport,
        "upload_image_to_uguu_for_temporary_public_url",
        fail_upload,
    )

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            str(local_image),
            bbox=[500, 0, 100, 1000],
        ),
    )

    assert result["visual_sources"] == []
    assert any(
        "bbox must have positive width" in issue for issue in result["issues"]
    )


def test_visual_jobs_carry_entity_reference_image():
    jobs = grounding_visual_jobs._expand_visual_query_jobs(
        ["Erling Haaland appearance"],
        context={
            "entities": [
                {
                    "text": "Erling Haaland",
                    "type": "person",
                    "reference_image": "/tmp/haaland-reference.jpg",
                    "reference_bbox": [100, 50, 900, 950],
                },
            ],
        },
        entities=[],
        max_visual_queries=4,
    )

    identity_jobs = [
        job for job in jobs if job.get("entity_name") == "Erling Haaland"
    ]
    assert identity_jobs
    assert identity_jobs[0]["reference_image"] == "/tmp/haaland-reference.jpg"
    assert identity_jobs[0]["reference_bbox"] == [100, 50, 900, 950]


def test_ground_prompt_context_prefers_serper_lens_for_reference_image_jobs(
    monkeypatch,
):
    lens_calls: list[dict] = []
    text_visual_calls: list[str] = []

    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "sources": [],
            "provider": "",
        }

    async def fake_search_visual_refs_by_image(
        image_ref,
        *,
        query="",
        max_sources=6,
        timeout=8.0,
    ):
        lens_calls.append({"image_ref": image_ref, "query": query})
        return {
            "query": query,
            "image_reference": image_ref,
            "issues": [],
            "visual_sources": [
                {
                    "url": "https://img.test/lens-match.jpg",
                    "title": "Lens match",
                    "provider": "serper_lens",
                    "query": query,
                },
            ],
            "provider": "serper_lens",
            "providers": ["serper_lens"],
            "providers_attempted": ["serper_lens"],
        }

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        text_visual_calls.append(query)
        return {
            "query": query,
            "issues": [],
            "visual_sources": [],
            "provider": "",
            "providers": [],
            "providers_attempted": [],
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
        "search_visual_refs_by_image",
        fake_search_visual_refs_by_image,
    )
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
            "哈兰德官方写真参考",
            queries=["Erling Haaland current appearance"],
            context={
                "entities": [
                    {
                        "text": "Erling Haaland",
                        "type": "person",
                        "reference_image": (
                            "https://public.test/haaland-ref.jpg"
                        ),
                    },
                ],
            },
            force=True,
            include_visuals=True,
            verify_visuals=False,
            max_sources=4,
        ),
    )

    assert lens_calls
    assert lens_calls[0]["image_ref"] == "https://public.test/haaland-ref.jpg"
    lens_sources = [
        source
        for source in result["visual_sources"]
        if source.get("provider") == "serper_lens"
    ]
    assert lens_sources
    # The lens-backed job must not fall through to text-query search.
    assert (
        "Erling Haaland official profile portrait clear face single person"
        not in text_visual_calls
    )
    assert "serper_lens" in result["visual_providers"]


def test_ground_prompt_context_confirms_lens_candidate_with_search_and_extract(
    monkeypatch,
):
    searched = []
    extracted = []

    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        searched.append(query)
        sources = []
        if query == "Eiffel Tower official identity":
            sources = [
                {
                    "title": "Eiffel Tower official facts",
                    "url": "https://example.test/eiffel",
                    "snippet": "A Paris landmark.",
                    "provider": "serper",
                    "query": query,
                    "score": None,
                },
            ]
        return {
            "query": query,
            "issues": [],
            "sources": sources,
            "provider": "serper" if sources else "",
        }

    async def fake_extract_web_pages(urls, *, goal="", timeout=8.0):
        extracted.append({"urls": urls, "goal": goal})
        return {
            "goal": goal,
            "issues": [],
            "sources": [
                {
                    "title": "Eiffel Tower official facts",
                    "url": urls[0],
                    "snippet": "The Eiffel Tower was completed in 1889.",
                    "content": "The Eiffel Tower was completed in 1889.",
                    "provider": "serper_scrape",
                    "query": goal,
                    "score": None,
                },
            ],
            "provider": "serper_scrape",
        }

    async def fake_search_visual_refs_by_image(
        image_ref,
        *,
        query="",
        max_sources=6,
        timeout=8.0,
    ):
        return {
            "query": query,
            "issues": [],
            "visual_sources": [
                {
                    "url": "https://img.test/eiffel.jpg",
                    "source_url": "https://example.test/lens-eiffel",
                    "title": "Eiffel Tower",
                    "provider": "serper_lens",
                    "query": query,
                },
            ],
            "provider": "serper_lens",
            "providers": ["serper_lens"],
            "providers_attempted": ["serper_lens"],
        }

    async def fake_stage(visual_sources, *, timeout=8.0):
        return visual_sources, {
            "status": "success",
            "downloaded_count": len(visual_sources),
            "failed_count": 0,
        }

    monkeypatch.setattr(web_grounding, "search_web", fake_search_web)
    monkeypatch.setattr(
        web_grounding,
        "extract_web_pages",
        fake_extract_web_pages,
    )
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs_by_image",
        fake_search_visual_refs_by_image,
    )
    monkeypatch.setattr(
        web_grounding,
        "stage_visual_grounding_sources",
        fake_stage,
    )

    result = asyncio.run(
        web_grounding.ground_prompt_context(
            "请识别并核实这个地标",
            queries=["unknown landmark"],
            context={
                "entities": [
                    {
                        "text": "unknown landmark",
                        "type": "place",
                        "strict_identity": True,
                        "reference_image": "https://public.test/reference.jpg",
                    },
                ],
            },
            force=True,
            include_visuals=True,
            verify_visuals=False,
            max_sources=6,
        ),
    )

    assert "Eiffel Tower official identity" in searched
    assert extracted[0]["urls"] == ["https://example.test/eiffel"]
    assert result["identity_confirmation"]["status"] == "confirmed"
    assert any(
        source["provider"] == "serper_scrape" for source in result["sources"]
    )


def test_ground_prompt_context_falls_back_to_text_search_when_lens_degrades(
    monkeypatch,
):
    text_visual_calls: list[str] = []

    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        return {
            "query": query,
            "issues": [],
            "sources": [],
            "provider": "",
        }

    async def degraded_search_visual_refs_by_image(
        image_ref,
        *,
        query="",
        max_sources=6,
        timeout=8.0,
    ):
        return {
            "query": query,
            "image_reference": image_ref,
            "issues": [
                "serper_lens:local_image_requires_creator_media_oss: "
                "configure creator_media_oss",
            ],
            "visual_sources": [],
            "provider": "",
            "providers": [],
            "providers_attempted": [],
        }

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        text_visual_calls.append(query)
        return {
            "query": query,
            "issues": [],
            "visual_sources": [
                {
                    "url": "https://img.test/text-match.jpg",
                    "title": "Text match",
                    "provider": "tavily",
                    "query": query,
                },
            ],
            "provider": "tavily",
            "providers": ["tavily"],
            "providers_attempted": ["tavily"],
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
        "search_visual_refs_by_image",
        degraded_search_visual_refs_by_image,
    )
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
            "哈兰德官方写真参考",
            queries=["Erling Haaland current appearance"],
            context={
                "entities": [
                    {
                        "text": "Erling Haaland",
                        "type": "person",
                        "reference_image": "/tmp/haaland-local.jpg",
                    },
                ],
            },
            force=True,
            include_visuals=True,
            verify_visuals=False,
            max_sources=4,
        ),
    )

    assert text_visual_calls
    assert any(
        issue.startswith("serper_lens:local_image_requires_creator_media_oss")
        for issue in result["issues"]
    )
    assert any(
        source.get("provider") == "tavily"
        for source in result["visual_sources"]
    )

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
from services.web_grounding import staging
from services.web_grounding import triage as grounding_triage
from services.web_grounding import verification
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


HAALAND_SOURCE = {
    "title": "Erling Haaland",
    "url": "https://example.test/haaland",
    "snippet": "Erling Haaland is a Norway international striker.",
    "provider": "fake",
}
HAALAND_IDENTITY_QUERY = (
    "Erling Haaland official profile portrait clear face single person"
)
IDOL_PRODUCER_QUERY = "Idol Producer official poster stage visual style"
LENS_MATCH = {
    "url": "https://img.test/match.jpg",
    "thumbnail_url": "",
    "source_url": "https://example.test/match",
    "title": "Match",
    "provider": "serper_lens",
}


def _search_web_stub(sources=None, issues=None, provider="", calls=None):
    """Factory for web_grounding.search_web stubs."""

    async def fake_search_web(query, *, max_sources=6, timeout=8.0):
        if calls is not None:
            calls.append(query)
        return {
            "query": query,
            "issues": list(issues or []),
            "sources": [dict(source, query=query) for source in sources or []],
            "provider": provider,
        }

    return fake_search_web


def _visual_refs_stub(
    sources=None,
    provider="dashscope_web_search_image",
    issues=None,
    calls=None,
    providers_attempted=None,
):
    """Factory for web_grounding.search_visual_refs stubs."""

    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        if calls is not None:
            calls.append((query, max_sources))
        picked = [
            dict(source, query=query)
            for source in list(sources or [])[:max_sources]
        ]
        return {
            "query": query,
            "issues": list(issues or []),
            "visual_sources": picked,
            "provider": provider if picked else "",
            "providers": [provider] if picked else [],
            "providers_attempted": (
                list(providers_attempted)
                if providers_attempted is not None
                else [provider]
            ),
        }

    return fake_search_visual_refs


async def _fake_download_visual_source(client, source, *, max_bytes):
    return {
        "payload": b"\x89PNG\r\n\x1a\nfake-image-bytes",
        "media_type": "image/png",
        "final_url": source["url"],
        "byte_size": 24,
    }


async def _stage_passthrough(visual_sources, *, timeout=8.0):
    return visual_sources, {
        "status": "success",
        "downloaded_count": len(visual_sources),
        "failed_count": 0,
    }


def _patch_media_part(monkeypatch):
    monkeypatch.setattr(
        verification,
        "multimodal_media_part",
        lambda url, media_type: {
            "type": "image_url",
            "image_url": {"url": url},
        },
    )


def _patch_visual_pipeline(
    monkeypatch,
    tmp_path,
    *,
    search_web,
    search_visual_refs,
    vlm_chat=None,
    api_key="key",
):
    """Wire the shared visual grounding pipeline stubs."""

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(web_grounding, "search_web", search_web)
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        search_visual_refs,
    )
    monkeypatch.setattr(
        staging,
        "download_visual_source",
        _fake_download_visual_source,
    )
    monkeypatch.setattr(
        verification.model_config,
        "get_web_grounding_model_api_key",
        lambda: api_key,
    )
    if vlm_chat is not None:
        monkeypatch.setattr(
            verification.vlm_model,
            "chat_completion",
            vlm_chat,
        )


def _patch_lens_key(monkeypatch, key="serper-key"):
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: key)


def _allow_public_url(monkeypatch):
    monkeypatch.setattr(
        provider_search,
        "_validate_public_remote_url",
        lambda value: value,
    )


def _local_lens_image(monkeypatch, tmp_path, oss_status=None):
    _patch_lens_key(monkeypatch, "key")
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    local_image = tmp_path / "reference.png"
    local_image.write_bytes(_png_bytes())
    if oss_status is not None:
        monkeypatch.setattr(
            provider_search._media_transport,
            "creator_oss_readiness",
            lambda: {"status": oss_status, "blockers": []},
        )
    return local_image


def _lens_stub(
    monkeypatch,
    expected_image_url=None,
    results=None,
    captured=None,
):
    async def fake_lens(client, image_url, limit, *, query=""):
        if expected_image_url is not None:
            assert image_url == expected_image_url
        if captured is not None:
            captured["image_url"] = image_url
            captured["query"] = query
        return [dict(item, query=query) for item in results or []]

    monkeypatch.setattr(provider_search, "_search_serper_lens", fake_lens)


@pytest.mark.parametrize(
    ("content_type", "content", "max_bytes", "match"),
    [
        ("image/png", b"\x89PNG\r\n\x1a\n" + (b"x" * 32), 16, "too large"),
        (
            "image/jpeg",
            b"\xff\xd8\xffnot-a-decodable-jpeg",
            1024,
            "cannot be decoded as an image",
        ),
    ],
    ids=["streamed-size-limit", "magic-bytes-cannot-decode"],
)
def test_download_visual_source_rejects_bad_payloads(
    content_type,
    content,
    max_bytes,
    match,
):
    async def handler(request):
        assert str(request.url) == "https://img.test/bad-payload.img"
        return httpx.Response(
            200,
            headers={"content-type": content_type},
            content=content,
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError, match=match):
                await staging.download_visual_source(
                    client,
                    {"url": "https://img.test/bad-payload.img"},
                    max_bytes=max_bytes,
                )

    asyncio.run(run())


@pytest.mark.parametrize(
    ("prompt", "needs_grounding", "expected_reason"),
    [
        ("请上网查一下 2026 World Cup top players 的资料", True, "explicit_search"),
        ("编一个虚构太空厨师的短片 prompt，风格温暖", False, None),
    ],
    ids=["explicit-search", "self-contained-fiction"],
)
def test_detect_grounding_needs_branches(
    prompt,
    needs_grounding,
    expected_reason,
):
    result = web_grounding.detect_grounding_needs(prompt)

    assert result["needs_grounding"] is needs_grounding
    if expected_reason:
        assert expected_reason in result["reasons"]
        assert result["queries"]
    else:
        assert result["queries"] == []


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


def test_ground_prompt_context_uses_search_results(monkeypatch):
    monkeypatch.setattr(
        web_grounding,
        "search_web",
        _search_web_stub(sources=[HAALAND_SOURCE]),
    )

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


@pytest.mark.parametrize(
    ("api_key", "expected_error", "match", "expected_calls"),
    [
        (
            "serper-test",
            adapters.SerperAuthenticationError,
            "HTTP 403",
            1,
        ),
        ("", RuntimeError, "SERPER_API_KEY", 0),
    ],
    ids=["auth-failure-without-retry", "missing-api-key"],
)
def test_search_serper_error_classification(
    monkeypatch,
    api_key,
    expected_error,
    match,
    expected_calls,
):
    if api_key:
        monkeypatch.setenv("SERPER_API_KEY", api_key)
    else:
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        monkeypatch.delenv("WEB_GROUNDING_SERPER_API_KEY", raising=False)
    calls = []

    async def handler(request):
        calls.append(request)
        # Authentication failures are fail-closed: no retry is attempted.
        return httpx.Response(403, json={"error": "denied"})

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await adapters._search_serper(client, "serper query", 3)

    with pytest.raises(expected_error, match=match):
        asyncio.run(run())
    assert len(calls) == expected_calls


@pytest.mark.parametrize(
    ("env_value", "expect_flag"),
    [(None, False), ("1", True)],
    ids=["omitted-by-default", "sent-when-opted-in"],
)
def test_search_tavily_safe_search_flag(monkeypatch, env_value, expect_flag):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    if env_value is None:
        monkeypatch.delenv("TAVILY_SAFE_SEARCH", raising=False)
    else:
        monkeypatch.setenv("TAVILY_SAFE_SEARCH", env_value)
    text_client = _FakeClient({"results": []})
    visual_client = _FakeClient({"images": []})

    asyncio.run(adapters._search_tavily(text_client, "Erling Haaland", 3))
    asyncio.run(
        adapters._search_tavily_visuals(visual_client, "Erling Haaland", 3),
    )

    if expect_flag:
        assert text_client.calls[0][1]["json"]["safe_search"] is True
        assert visual_client.calls[0][1]["json"]["safe_search"] is True
    else:
        # Tavily rejects safe_search outside enterprise plans with HTTP 403.
        assert "safe_search" not in text_client.calls[0][1]["json"]
        assert "safe_search" not in visual_client.calls[0][1]["json"]


@pytest.mark.parametrize(
    (
        "tavily_key",
        "serper_key",
        "dashscope_key",
        "behaviors",
        "expected_provider",
        "expected_attempted",
        "expected_issues",
    ),
    [
        (
            "tavily-key",
            "serper-key",
            "dashscope-key",
            {"tavily": "ok", "serper": "fail", "dashscope_web_search": "fail"},
            "tavily",
            ["tavily"],
            [],
        ),
        (
            "",
            "serper-key",
            "dashscope-key",
            {
                "tavily": "fail",
                "serper": "error",
                "dashscope_web_search": "ok",
            },
            "dashscope_web_search",
            ["serper", "dashscope_web_search"],
            [
                "serper:RuntimeError: serper quota exceeded",
                "serper:no_text_sources",
            ],
        ),
        (
            "",
            "",
            "",
            {
                "tavily": "fail",
                "serper": "fail",
                "dashscope_web_search": "fail",
            },
            "",
            [],
            [
                "tavily_api_key_missing",
                "serper_api_key_missing",
                "dashscope_web_search_api_key_missing",
            ],
        ),
    ],
    ids=[
        "tavily-succeeds-without-fallback",
        "serper-error-falls-through-to-dashscope",
        "all-provider-keys-missing",
    ],
)
def test_search_web_provider_fallback_chain(
    monkeypatch,
    tavily_key,
    serper_key,
    dashscope_key,
    behaviors,
    expected_provider,
    expected_attempted,
    expected_issues,
):
    monkeypatch.setattr(provider_search, "_tavily_api_key", lambda: tavily_key)
    monkeypatch.setattr(provider_search, "_serper_api_key", lambda: serper_key)
    monkeypatch.setattr(
        provider_search,
        "_dashscope_web_search_api_key",
        lambda: dashscope_key,
    )

    def make_provider(name, url):
        async def provider(client, query, limit):
            behavior = behaviors[name]
            if behavior == "fail":
                raise AssertionError(f"{name} should not run in this scenario")
            if behavior == "error":
                raise RuntimeError("serper quota exceeded")
            return [
                {
                    "title": f"{name} source",
                    "url": url,
                    "snippet": "source",
                    "provider": name,
                    "query": query,
                },
            ]

        return provider

    monkeypatch.setattr(
        provider_search,
        "_search_tavily",
        make_provider("tavily", "https://example.test/tavily"),
    )
    monkeypatch.setattr(
        provider_search,
        "_search_serper",
        make_provider("serper", "https://example.test/serper"),
    )
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web",
        make_provider("dashscope_web_search", "https://example.test/qwen"),
    )

    result = asyncio.run(web_grounding.search_web("Erling Haaland"))

    assert result["provider"] == expected_provider
    assert result["providers_attempted"] == expected_attempted
    for issue in expected_issues:
        assert issue in result["issues"]
    if expected_provider:
        assert result["providers"] == [expected_provider]
        assert result["sources"][0]["provider"] == expected_provider
    else:
        assert result["sources"] == []


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


@pytest.mark.parametrize(
    (
        "tavily_key",
        "serper_key",
        "behaviors",
        "expected_providers",
        "expected_attempted",
        "expected_urls",
        "expected_issues",
    ),
    [
        (
            "tvly-test",
            "",
            {"tavily": "img", "serper": "fail", "dashscope": "img"},
            ["tavily", "dashscope_web_search_image"],
            ["tavily", "dashscope_web_search_image"],
            ["https://img.test/tavily.jpg", "https://img.test/qwen.jpg"],
            [],
        ),
        (
            "",
            "serper-test",
            {"tavily": "fail", "serper": "error", "dashscope": "img"},
            ["dashscope_web_search_image"],
            ["serper", "dashscope_web_search_image"],
            ["https://img.test/qwen.jpg"],
            ["serper_images:RuntimeError: serper quota exceeded"],
        ),
    ],
    ids=[
        "dashscope-supplements-insufficient-tavily-results",
        "serper-error-reported-then-dashscope",
    ],
)
def test_search_visual_refs_provider_fallback_chain(
    monkeypatch,
    tavily_key,
    serper_key,
    behaviors,
    expected_providers,
    expected_attempted,
    expected_urls,
    expected_issues,
):
    for name in (
        "WEB_GROUNDING_IMAGE_PROVIDERS",
        "WEB_GROUNDING_VISUAL_PROVIDERS",
        "WEB_GROUNDING_TAVILY_API_KEY",
        "WEB_GROUNDING_SERPER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")
    if tavily_key:
        monkeypatch.setenv("TAVILY_API_KEY", tavily_key)
    else:
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    if serper_key:
        monkeypatch.setenv("SERPER_API_KEY", serper_key)
    else:
        monkeypatch.delenv("SERPER_API_KEY", raising=False)

    def make_visual_provider(name, provider_name, url):
        async def provider(client, query, limit):
            behavior = behaviors[name]
            if behavior == "fail":
                raise AssertionError(f"{name} should not run in this scenario")
            if behavior == "error":
                raise RuntimeError("serper quota exceeded")
            return [
                {
                    "url": url,
                    "title": f"{name} image",
                    "provider": provider_name,
                    "query": query,
                },
            ]

        return provider

    monkeypatch.setattr(
        provider_search,
        "_search_tavily_visuals",
        make_visual_provider(
            "tavily",
            "tavily",
            "https://img.test/tavily.jpg",
        ),
    )
    monkeypatch.setattr(
        provider_search,
        "_search_serper_visuals",
        make_visual_provider(
            "serper",
            "serper",
            "https://img.test/serper.jpg",
        ),
    )
    monkeypatch.setattr(
        provider_search,
        "_search_dashscope_web_search_image_visuals",
        make_visual_provider(
            "dashscope",
            "dashscope_web_search_image",
            "https://img.test/qwen.jpg",
        ),
    )

    result = asyncio.run(web_grounding.search_visual_refs("Erling Haaland"))

    assert result["providers"] == expected_providers
    assert result["providers_attempted"] == expected_attempted
    assert result["provider"] == expected_providers[-1]
    assert [
        source["url"] for source in result["visual_sources"]
    ] == expected_urls
    for issue in expected_issues:
        assert issue in result["issues"]


@pytest.mark.parametrize(
    ("exception", "expected_attempts", "expected_issue", "absent_issue"),
    [
        (
            httpx.ReadTimeout("slow qwen image search"),
            2,
            "dashscope_web_search_image:retry_succeeded:2",
            None,
        ),
        (
            ValueError("invalid image search payload"),
            1,
            "dashscope_web_search_image:ValueError: invalid image search payload",
            "dashscope_web_search_image:retry_exhausted",
        ),
    ],
    ids=["read-timeout-is-retried", "nonretryable-error-reported"],
)
def test_search_visual_refs_dashscope_error_retry_policy(
    monkeypatch,
    exception,
    expected_attempts,
    expected_issue,
    absent_issue,
):
    for name in (
        "WEB_GROUNDING_IMAGE_PROVIDERS",
        "WEB_GROUNDING_VISUAL_PROVIDERS",
        "TAVILY_API_KEY",
        "WEB_GROUNDING_TAVILY_API_KEY",
        "SERPER_API_KEY",
        "WEB_GROUNDING_SERPER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TEXT_API_KEY", "dashscope-test")
    attempts = 0

    async def flaky_dashscope(client, query, limit):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise exception
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

    assert attempts == expected_attempts
    assert expected_issue in result["issues"]
    if absent_issue:
        assert absent_issue not in result["issues"]
    else:
        assert result["providers"] == ["dashscope_web_search_image"]
        assert result["provider"] == "dashscope_web_search_image"
        assert (
            result["visual_sources"][0]["url"]
            == "https://img.test/haaland.jpg"
        )


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
    assert haaland["query"] == HAALAND_IDENTITY_QUERY

    idol_producer = by_name["Idol Producer"]
    assert idol_producer["entity_type"] == "ip"
    assert idol_producer["usage"] == "context"
    assert idol_producer["strict_identity"] is False
    assert idol_producer["query"] == IDOL_PRODUCER_QUERY


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
        "Erling Haaland": HAALAND_IDENTITY_QUERY,
        "Rodrigo De Paul": "Rodrigo De Paul official profile portrait clear face single person",
    }
    assert all(
        "2024" not in query and "fashion" not in query
        for query in queries.values()
    )
    assert all(job["strict_identity"] for job in jobs if job["entity_name"])

    context_jobs = [job for job in jobs if not job["entity_name"]]
    assert [job["query"] for job in context_jobs] == [
        "idol survival show stage performance visual style",
    ]


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
    _patch_media_part(monkeypatch)
    sources = [
        {
            "index": 1,
            "local_url": "file:///tmp/reference.jpg",
            "vlm_image_url": "file:///tmp/reference.jpg",
        },
    ]

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


def test_ground_prompt_context_exposes_authoritative_normalized_query_plan(
    monkeypatch,
):
    text_calls = []
    visual_calls = []

    monkeypatch.setattr(
        web_grounding,
        "search_web",
        _search_web_stub(calls=text_calls),
    )
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        _visual_refs_stub(calls=visual_calls, providers_attempted=[]),
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
        HAALAND_IDENTITY_QUERY,
        "Rodrigo De Paul official profile portrait clear face single person",
        "idol training show Chinese variety show stage performance",
    ]
    assert result["query_plan"] == {
        "text": result["queries"],
        "visual": result["visual_queries"],
    }
    assert text_calls == result["queries"]
    assert [query for query, _ in visual_calls] == result["visual_queries"]


def test_ground_prompt_context_can_verify_visual_sources_with_vlm(
    monkeypatch,
    tmp_path,
):
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

    _patch_visual_pipeline(
        monkeypatch,
        tmp_path,
        search_web=_search_web_stub(sources=[HAALAND_SOURCE]),
        search_visual_refs=_visual_refs_stub(
            sources=[
                {
                    "index": 1,
                    "url": "https://img.test/haaland-good.jpg",
                    "title": "Haaland portrait",
                },
                {
                    "index": 2,
                    "url": "https://img.test/wrong.jpg",
                    "title": "Wrong player",
                },
            ],
        ),
        vlm_chat=fake_vlm_chat,
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


def test_strict_identity_visual_grounding_degrades_when_no_photo_is_accepted(
    monkeypatch,
    tmp_path,
):
    async def fake_search_visual_refs(query, *, max_sources=6, timeout=8.0):
        # Every query (including strict-identity retries) only yields fan art.
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

    async def fake_vlm_chat(content, **kwargs):
        return json.dumps(
            {
                "selected": [],
                "rejected": [],
                "summary": "no accepted strict identity photo",
            },
        )

    _patch_visual_pipeline(
        monkeypatch,
        tmp_path,
        search_web=_search_web_stub(),
        search_visual_refs=fake_search_visual_refs,
        vlm_chat=fake_vlm_chat,
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


@pytest.mark.parametrize(
    ("recovers", "expected_urls"),
    [(True, ["https://img.test/eiffel.jpg"]), (False, [])],
    ids=[
        "retries-transient-empty-organic",
        "gives-up-after-bounded-empty-retries",
    ],
)
def test_search_serper_lens_empty_organic_retry_policy(
    monkeypatch,
    recovers,
    expected_urls,
):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")
    monkeypatch.delenv("SERPER_LENS_URL", raising=False)
    monkeypatch.setattr(
        adapters,
        "SERPER_LENS_EMPTY_RETRY_BACKOFF_SECONDS",
        0.0,
    )
    empty = httpx.Response(200, json={"organic": []})
    populated = httpx.Response(
        200,
        json={
            "organic": [
                {
                    "title": "Eiffel Tower",
                    "link": "https://example.test/eiffel",
                    "imageUrl": "https://img.test/eiffel.jpg",
                },
            ],
        },
    )

    async def run():
        async with httpx.AsyncClient() as client:
            return await adapters._search_serper_lens(
                client,
                "https://public.test/reference.jpg",
                3,
                query="Eiffel Tower",
            )

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://google.serper.dev/lens")
        if recovers:
            route.mock(side_effect=[empty, populated])
        else:
            route.mock(return_value=empty)
        results = asyncio.run(run())

    assert route.call_count == (
        2 if recovers else adapters.SERPER_LENS_EMPTY_RESULT_ATTEMPTS
    )
    assert [source["url"] for source in results] == expected_urls


def test_search_visual_refs_by_image_uses_public_http_url(monkeypatch):
    _patch_lens_key(monkeypatch)
    _allow_public_url(monkeypatch)
    captured = {}
    _lens_stub(monkeypatch, results=[LENS_MATCH], captured=captured)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            "https://public.test/reference.jpg",
            query="Erling Haaland",
        ),
    )

    assert captured == {
        "image_url": "https://public.test/reference.jpg",
        "query": "Erling Haaland",
    }
    assert result["provider"] == "serper_lens"
    assert result["providers"] == ["serper_lens"]
    assert result["providers_attempted"] == ["serper_lens"]
    assert result["visual_sources"][0]["url"] == "https://img.test/match.jpg"
    assert result["issues"] == []


@pytest.mark.parametrize(
    ("serper_key", "image_ref", "issue_prefix"),
    [
        ("", "https://public.test/reference.jpg", "serper_api_key_missing"),
        (
            "serper-key",
            "oss://temp/reference.jpg",
            "serper_lens:oss_url_not_public",
        ),
        (
            "serper-key",
            "http://127.0.0.1/private.jpg",
            "serper_lens:non_public_image_url",
        ),
    ],
    ids=["missing-serper-key", "dashscope-oss-url", "private-http-url"],
)
def test_search_visual_refs_by_image_rejects_unusable_references(
    monkeypatch,
    serper_key,
    image_ref,
    issue_prefix,
):
    _patch_lens_key(monkeypatch, serper_key)

    async def fail_lens(*args, **kwargs):
        raise AssertionError(
            "unusable references must never reach Serper Lens",
        )

    monkeypatch.setattr(provider_search, "_search_serper_lens", fail_lens)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(image_ref),
    )

    assert result["visual_sources"] == []
    assert result["providers_attempted"] == []
    assert any(issue.startswith(issue_prefix) for issue in result["issues"])


def test_search_visual_refs_by_image_presigns_local_media_when_oss_ready(
    monkeypatch,
    tmp_path,
):
    local_image = _local_lens_image(monkeypatch, tmp_path, oss_status="ready")
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
    _lens_stub(
        monkeypatch,
        results=[dict(LENS_MATCH, source_url="")],
        captured=captured,
    )

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            str(local_image),
            query="local reference",
        ),
    )

    assert uploaded == {"content": _png_bytes(), "filename": "reference.png"}
    assert captured["image_url"].startswith("https://bucket.test/")
    assert result["provider"] == "serper_lens"
    # The signed URL must never leak into the result payload.
    assert result["query"] == "local reference"
    assert result["image_reference"] == ""
    assert result["image_reference_kind"] == "local_media"
    assert result["image_transport"] == "creator_oss"


def test_ground_prompt_context_prefers_serper_lens_for_reference_image_jobs(
    monkeypatch,
):
    lens_calls = []
    text_visual_calls = []

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

    monkeypatch.setattr(web_grounding, "search_web", _search_web_stub())
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs_by_image",
        fake_search_visual_refs_by_image,
    )
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        _visual_refs_stub(calls=text_visual_calls, providers_attempted=[]),
    )
    monkeypatch.setattr(
        web_grounding,
        "stage_visual_grounding_sources",
        _stage_passthrough,
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
                        "reference_image": "https://public.test/haaland-ref.jpg",
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
    assert [
        source
        for source in result["visual_sources"]
        if source.get("provider") == "serper_lens"
    ]
    # The lens-backed job must not fall through to text-query search.
    assert HAALAND_IDENTITY_QUERY not in [
        query for query, _ in text_visual_calls
    ]
    assert "serper_lens" in result["visual_providers"]


def test_ground_prompt_context_falls_back_to_text_search_when_lens_degrades(
    monkeypatch,
):
    text_visual_calls = []

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
                "serper_lens:local_image_requires_creator_media_oss: configure creator_media_oss",
            ],
            "visual_sources": [],
            "provider": "",
            "providers": [],
            "providers_attempted": [],
        }

    monkeypatch.setattr(web_grounding, "search_web", _search_web_stub())
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs_by_image",
        degraded_search_visual_refs_by_image,
    )
    monkeypatch.setattr(
        web_grounding,
        "search_visual_refs",
        _visual_refs_stub(
            sources=[
                {
                    "url": "https://img.test/text-match.jpg",
                    "title": "Text match",
                    "provider": "tavily",
                },
            ],
            provider="tavily",
            calls=text_visual_calls,
        ),
    )
    monkeypatch.setattr(
        web_grounding,
        "stage_visual_grounding_sources",
        _stage_passthrough,
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

# -*- coding: utf-8 -*-
"""Cross-cutting model platform contracts."""

import asyncio
import json

import pytest

from qwenpaw.providers import model_catalog
from qwenpaw.providers.adapters.cache_policy import (
    cache_request,
    mark_stable_prefix,
)
from qwenpaw.providers.adapters.request_context import (
    model_session,
    session_header,
)
from qwenpaw.providers.model_ranking import recommend
from qwenpaw.providers.multimodal_prober import ProbeResult
from qwenpaw.providers.openai_provider import OpenCodeProvider


def test_shards_load_only_requested_provider(monkeypatch):
    calls = []
    read = model_catalog._read_shard

    def tracked(path, modified, digest):
        calls.append(path.name)
        return read(path, modified, digest)

    monkeypatch.setattr(model_catalog, f"_read_shard", tracked)
    document = model_catalog._read_document(
        model_catalog.PACKAGED_CATALOG_PATH,
        (f"anthropic",),
    )
    assert set(document.providers) == {f"anthropic"}
    assert calls == [f"anthropic.json"]


def test_shard_integrity_rejects_changed_content(tmp_path):
    shard = tmp_path / f"provider.json"
    shard.write_text(json.dumps({f"models": []}))
    with pytest.raises(ValueError, match=f"SHA-256"):
        model_catalog._read_shard(shard, 0, f"0" * 64)


def test_quality_gate_keeps_unknown_and_estimated_manual():
    assert recommend(f"z-ai/glm-5.3-flash", f"free", True, True).eligible
    assert not recommend(f"z-ai/glm-5.3-flash", f"paid", True, True).eligible
    assert not recommend(f"z-ai/glm-5.3-flash", f"free", None, True).eligible
    assert recommend(None, f"free", True, True).reason == f"unranked"
    assert (
        recommend(
            f"stepfun/step-3.7-flash",
            f"free",
            True,
            True,
        ).reason
        == f"estimated_score"
    )


@pytest.mark.parametrize(
    f"message",
    [
        f"Probe failed: invalid API key 401",
        f"Probe inconclusive: 429",
        f"Probe failed: timed out",
        f"Model did not recognise image",
    ],
)
def test_inconclusive_probe_does_not_claim_unsupported(message):
    result = ProbeResult(supports_image=False, image_message=message)
    assert result.supports_image is None
    assert result.supports_multimodal is None


async def test_provider_session_headers_are_isolated():
    provider = OpenCodeProvider(id=f"opencode", name=f"OpenCode")

    async def call(session):
        with model_session({f"session_id": session}, f"unused"):
            first = provider.prepare_request(f"demo", f"chat", {})
            await asyncio.sleep(0)
            second = provider.prepare_request(f"demo", f"chat", {})
            assert first == second
            return first[f"extra_headers"][f"x-opencode-session"]

    a, b = await asyncio.gather(call(f"a"), call(f"b"))
    assert a != b
    assert session_header(f"fallback") == f"fallback"
    assert not provider.custom_headers


def test_cache_breakpoints_preserve_input_and_skip_dynamic_suffix():
    messages = [
        {f"role": f"system", f"content": f"stable"},
        {f"role": f"user", f"content": f"changes"},
    ]
    result = mark_stable_prefix(messages, responses=True)
    assert result[0][f"content"][0][f"prompt_cache_breakpoint"] == {
        f"mode": f"explicit",
    }
    assert result[1] == messages[1]
    assert messages[0][f"content"] == f"stable"


def test_cache_options_use_extra_body_and_do_not_leak_protocol():
    options = {f"prompt_cache_options": {f"mode": f"explicit"}}
    result = cache_request(
        options, f"responses", frozenset({f"openai_explicit"})
    )
    assert result == {f"extra_body": options}
    with pytest.raises(ValueError):
        cache_request(options, f"chat", frozenset())


def test_default_bootstrap_does_not_read_full_shards(monkeypatch):
    def unexpected(*args):
        raise AssertionError(f"Default startup loaded a full shard")

    monkeypatch.setattr(model_catalog, f"_read_shard", unexpected)
    models = model_catalog.load_model_catalog(defaults_only=True)
    assert models[f"openai"]


def test_atomic_shard_update_and_new_template_lookup(tmp_path, monkeypatch):
    destination = tmp_path / f"index.json"
    from qwenpaw.providers.model_info import ModelInfo

    document = model_catalog.CatalogDocument(
        catalog_version=f"2026.09.18.1",
        providers={
            f"new-vendor": model_catalog.CatalogProvider(
                template_owner=True,
                models=[ModelInfo(id=f"new-model", name=f"New")],
            )
        },
    )
    model_catalog.install_catalog_document(document, destination)
    assert model_catalog._read_document(destination) == document
    monkeypatch.setattr(model_catalog, f"METADATA_CACHE_PATH", destination)
    assert f"new-vendor" in model_catalog.matching_catalog_keys(
        f"custom",
        f"https://custom.example",
        f"new-model",
        None,
    )
    old = destination.read_bytes()
    real = model_catalog.install_catalog_payload

    def broken(payload, target, **kwargs):
        if target == destination:
            raise OSError(f"Interrupted before index publication")
        return real(payload, target, **kwargs)

    monkeypatch.setattr(model_catalog, f"install_catalog_payload", broken)
    with pytest.raises(OSError):
        model_catalog.install_catalog_document(document, destination)
    assert destination.read_bytes() == old


@pytest.mark.parametrize(
    f"model_id,protocol",
    [
        (f"union-alpha", f"anthropic"),
        (f"muse-spark-1.3-contributor-free", f"responses"),
        (f"mimo-v2.5-free", f"chat"),
    ],
)
def test_opencode_uses_native_protocol_without_losing_session(
    model_id, protocol
):
    provider = OpenCodeProvider(
        id=f"opencode",
        name=f"OpenCode",
        api_key=f"test",
        base_url=f"https://opencode.ai/zen/v1",
    )
    native = provider._protocol_provider(model_id)
    assert provider.model_protocol(model_id) == protocol
    assert native.wire_protocol == protocol
    assert native.api_key == provider.api_key
    assert native._request_session == provider._request_session
    assert native.get_chat_model_instance(model_id) is not None


@pytest.mark.parametrize(
    f"kwargs",
    [
        {f"extra_body": {f"prompt_cache_options": {f"mode": f"explicit"}}},
        {f"extra_body": {f"cache_control": {f"type": f"ephemeral"}}},
    ],
)
def test_extra_body_cannot_bypass_cache_protocol_validation(kwargs):
    with pytest.raises(ValueError):
        cache_request(kwargs, f"chat", frozenset())


async def test_deepseek_nonstream_cache_header_is_request_local():
    import httpx
    from agentscope.credential import OpenAICredential
    from agentscope.message import Msg
    from qwenpaw.providers.openai_chat_model_compat import (
        OpenAIChatModelCompat,
    )
    from qwenpaw.providers.adapters.usage import CACHE_RESPONSE_HEADERS

    def handler(request):
        return httpx.Response(
            200,
            headers={f"x-ds-cache-status": f"hit"},
            json={
                f"id": f"response",
                f"object": f"chat.completion",
                f"created": 0,
                f"model": f"deepseek-chat",
                f"choices": [
                    {
                        f"index": 0,
                        f"message": {f"role": f"assistant", f"content": f"OK"},
                        f"finish_reason": f"stop",
                    }
                ],
                f"usage": {
                    f"prompt_tokens": 12,
                    f"completion_tokens": 1,
                    f"total_tokens": 13,
                    f"prompt_cache_hit_tokens": 10,
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        model = OpenAIChatModelCompat(
            credential=OpenAICredential(
                api_key=f"test", base_url=f"https://example.test"
            ),
            model=f"deepseek-chat",
            stream=False,
            capture_cache_status=True,
            client_kwargs={f"http_client": client},
        )
        response = await model(
            [
                Msg(
                    name=f"user",
                    content=[{f"type": f"text", f"text": f"hi"}],
                    role=f"user",
                )
            ]
        )
    assert response.usage.cache_input_tokens == 10
    assert response.usage.metadata[f"provider_cache_status"] == f"hit"
    assert CACHE_RESPONSE_HEADERS.get() == {}


async def test_manual_add_overrides_ranking_gate_and_survives_restore():
    from qwenpaw.providers.model_info import ModelInfo
    from qwenpaw.providers.provider_manager import ProviderManager

    model = ModelInfo(id=f"unknown-free", name=f"Unknown", is_free=True)
    provider = OpenCodeProvider(
        id=f"opencode",
        name=f"OpenCode",
        models=[model],
        api_key=f"test",
    )
    assert provider.configured_models() == []
    assert provider.discovery_candidates()[0].id == model.id
    success, _ = await provider.add_model(model.model_copy(deep=True))
    assert success
    assert provider.configured_models()[0].source == f"user"
    restored = OpenCodeProvider(
        id=f"opencode",
        name=f"OpenCode",
        models=[ModelInfo(id=model.id, name=model.name, is_free=True)],
    )
    ProviderManager._restore_builtin_provider(restored, provider)
    assert restored.configured_models()[0].source == f"user"


def test_rankings_reject_nonfinite_evidence():
    from qwenpaw.providers.model_ranking import RankingEvidence

    with pytest.raises(ValueError):
        RankingEvidence(
            model_id=f"fake",
            metric=f"AA",
            version=f"4.3",
            score=float(f"nan"),
            checked_at=f"2026-09-18",
            source=f"https://example.test",
        )

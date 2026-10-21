# -*- coding: utf-8 -*-
"""TypeSafe evaluation uses provider settings and validates responses."""

# pylint: disable=protected-access

import json
from types import SimpleNamespace

import httpx
import pytest

from qwenpaw.providers.typesafe_provider import (
    TypeSafeEvaluationError,
    TypeSafeProvider,
)


@pytest.fixture(name="provider")
def configured_provider():
    return TypeSafeProvider(
        id="typesafe",
        name="TypeSafe",
        api_key="provider-key",
        base_url="https://proxy.example/v1",
        custom_headers={"X-Project": "demo"},
    )


@pytest.mark.asyncio
async def test_provider_key_precedes_legacy_credential(provider):
    assert await provider._evaluation_api_key() == "provider-key"


@pytest.mark.asyncio
async def test_legacy_credential_remains_usable(monkeypatch, provider):
    class LegacyStore:
        def __init__(self, _path):
            pass

        async def get(self, _ref):
            return SimpleNamespace(secrets={"api_key": "legacy-key"})

    provider.api_key = ""
    monkeypatch.setattr(
        "qwenpaw.providers.typesafe_provider.AsyncCredentialStore",
        LegacyStore,
    )
    assert await provider._evaluation_api_key() == "legacy-key"


@pytest.mark.asyncio
async def test_evaluate_uses_provider_settings(monkeypatch, provider):
    original_client = httpx.AsyncClient

    def handler(request):
        body = json.loads(request.content)
        assert request.url.host == "proxy.example"
        assert request.url.path == "/v1/systemone"
        assert request.headers["Authorization"] == "Bearer provider-key"
        assert request.headers["X-Project"] == "demo"
        assert body == {
            "model": "jev-2",
            "state": {"summary": "conversation segment"},
            "questions": {
                "keep_in_context": {
                    "type": "noul",
                    "instructions": "Keep this in active context?",
                },
            },
        }
        return httpx.Response(
            200,
            json={
                "model": "jev-2",
                "answers": {"keep_in_context": {"type": "noul", "noul": 0.8}},
                "usage": {"input_tokens": 20, "output_tokens": 4},
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    result = await provider.evaluate(
        state={"summary": "conversation segment"},
        model="jev-2",
        questions={
            "keep_in_context": {
                "type": "noul",
                "instructions": "Keep this in active context?",
            },
        },
    )
    assert result["answers"]["keep_in_context"]["noul"] == 0.8


@pytest.mark.asyncio
async def test_missing_key_is_explicit_error(monkeypatch, provider):
    async def no_key(_provider):
        return None

    monkeypatch.setattr(TypeSafeProvider, "_evaluation_api_key", no_key)
    with pytest.raises(TypeSafeEvaluationError, match="not configured"):
        await provider.evaluate(
            state="x",
            questions={"q": {"type": "noul", "instructions": "x"}},
        )


@pytest.mark.asyncio
async def test_invalid_response_envelope_is_rejected(monkeypatch, provider):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={
                        "model": "jev-2",
                        "answers": {"q": {"type": "score"}},
                    },
                ),
            ),
            **kwargs,
        ),
    )
    with pytest.raises(
        TypeSafeEvaluationError,
        match="Invalid response envelope",
    ):
        await provider.evaluate(
            state="x",
            questions={"q": {"type": "noul", "instructions": "x"}},
        )

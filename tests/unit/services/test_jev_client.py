# -*- coding: utf-8 -*-
"""The Jev transport accepts questions outside the security domain."""

import json
from types import SimpleNamespace

import httpx
import pytest

from qwenpaw.services.jev import (
    JevClient,
    JevRequest,
    JevServiceError,
    _provider_settings,
)


def test_provider_settings_use_selected_decision_model(monkeypatch):
    from qwenpaw.providers.provider_manager import ProviderManager

    provider = SimpleNamespace(
        api_key="provider-key",
        base_url="https://proxy.example/v1",
        custom_headers={"X-Project": "demo"},
        enabled=True,
    )
    manager = SimpleNamespace(
        get_provider=lambda provider_id: provider
        if provider_id == "typesafe"
        else None,
        default_models={
            "decision": SimpleNamespace(provider_id="typesafe", model="jev-2"),
        },
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    assert _provider_settings() == (
        "provider-key",
        "https://proxy.example/v1",
        "jev-2",
        {"X-Project": "demo"},
    )


@pytest.mark.asyncio
async def test_provider_key_precedes_legacy_credential(monkeypatch):
    from qwenpaw.services import jev

    monkeypatch.setattr(
        jev,
        "_provider_settings",
        lambda: (
            "provider-key",
            "https://api.typesafe.ai/v1",
            "jev-latest",
            {},
        ),
    )
    assert await jev.get_api_key() == "provider-key"


@pytest.mark.asyncio
async def test_legacy_credential_remains_usable(monkeypatch):
    from qwenpaw.services import jev

    class LegacyStore:
        async def get(self, _ref):
            return SimpleNamespace(secrets={"api_key": "legacy-key"})

    monkeypatch.setattr(
        jev,
        "_provider_settings",
        lambda: ("", "https://api.typesafe.ai/v1", "jev-latest", {}),
    )
    monkeypatch.setattr(jev, "_credential_store", LegacyStore)
    assert await jev.get_api_key() == "legacy-key"


@pytest.mark.asyncio
async def test_context_management_question_uses_generic_client(monkeypatch):
    import qwenpaw.services.jev as service

    async def key():
        return "test-key"

    monkeypatch.setattr(service, "get_api_key", key)
    monkeypatch.setattr(
        service,
        "_provider_settings",
        lambda: ("test-key", "https://proxy.example/v1", "jev-2", {}),
    )
    original_client = httpx.AsyncClient

    def handler(request):
        body = json.loads(request.content)
        assert request.url.host == "proxy.example"
        assert request.url.path == "/v1/systemone"
        assert body["model"] == "jev-2"
        assert body["state"] == {"summary": "conversation segment"}
        assert body["questions"]["keep_in_context"]["type"] == "noul"
        return httpx.Response(
            200,
            json={
                "model": "jev-1",
                "answers": {"keep_in_context": {"type": "noul", "noul": 0.8}},
                "usage": {"input_tokens": 20, "output_tokens": 4},
            },
        )

    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    result = await JevClient().evaluate(
        JevRequest(
            state={"summary": "conversation segment"},
            questions={
                "keep_in_context": {
                    "type": "noul",
                    "instructions": "Keep this in active context?",
                },
            },
        ),
    )
    assert result.answers["keep_in_context"]["noul"] == 0.8


@pytest.mark.asyncio
async def test_missing_key_is_explicit_error(monkeypatch):
    from qwenpaw.services import jev

    async def no_key():
        return None

    monkeypatch.setattr(jev, "get_api_key", no_key)
    monkeypatch.setattr(
        jev,
        "_provider_settings",
        lambda: ("", "https://api.typesafe.ai/v1", "jev-latest", {}),
    )
    with pytest.raises(JevServiceError, match="not configured"):
        await JevClient().evaluate(
            JevRequest(
                state="x",
                questions={"q": {"type": "noul", "instructions": "x"}},
            ),
        )

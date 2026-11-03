# -*- coding: utf-8 -*-
"""Text model protocol dispatch and keyless free-tier support."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import json as json_module

import pytest

from models import text_model
from utils.exceptions import ModelError

pytestmark = pytest.mark.unit


def _patch_config(monkeypatch, *, protocol: str, api_key: str) -> None:
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_api_key",
        lambda: api_key,
    )
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_model_name",
        lambda: "test-model",
    )
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_protocol",
        lambda: protocol,
    )
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_base_url",
        lambda: "https://gateway.example.com/v1",
    )


def _fake_httpx(monkeypatch, captured: dict) -> None:
    class FakeResponse:
        status_code = 200

        @property
        def text(self) -> str:
            return ""

        def json(self) -> dict:
            return {
                "choices": [
                    {"message": {"content": "pong"}},
                ],
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, body=json)
            return FakeResponse()

    class FakeSlot:
        def __init__(self, _kind):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(text_model.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(text_model, "model_slot", FakeSlot)


def test_keyless_openai_protocol_omits_authorization_header(
    monkeypatch,
) -> None:
    # OpenCode Zen ``*-free`` models accept unauthenticated requests; an
    # empty Bearer header would be rejected as an invalid key.
    _patch_config(monkeypatch, protocol="OpenCode", api_key="")
    captured: dict = {}
    _fake_httpx(monkeypatch, captured)

    result = asyncio.run(text_model.chat_completion("ping"))

    assert result == "pong"
    assert captured["url"] == "https://gateway.example.com/v1/chat/completions"
    assert "Authorization" not in captured["headers"]


def test_openai_protocol_sends_bearer_when_key_present(monkeypatch) -> None:
    _patch_config(monkeypatch, protocol="OpenAI 协议", api_key="sk-test")
    captured: dict = {}
    _fake_httpx(monkeypatch, captured)

    asyncio.run(text_model.chat_completion("ping"))

    assert captured["headers"]["Authorization"] == "Bearer sk-test"


def test_anthropic_protocol_still_requires_api_key(monkeypatch) -> None:
    _patch_config(monkeypatch, protocol="Anthropic Claude", api_key="")

    with pytest.raises(ModelError):
        asyncio.run(text_model.chat_completion("ping"))


def test_gemini_protocol_still_requires_api_key(monkeypatch) -> None:
    _patch_config(monkeypatch, protocol="Google Gemini", api_key="")

    with pytest.raises(ModelError):
        asyncio.run(text_model.chat_completion("ping"))


def test_anthropic_protocol_dispatches_to_messages_endpoint(
    monkeypatch,
) -> None:
    _patch_config(monkeypatch, protocol="Anthropic Claude", api_key="sk-test")
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_model_name",
        lambda: "MiniMax-M2.7",
    )
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        @property
        def text(self) -> str:
            return ""

        def json(self) -> dict:
            return {"content": [{"type": "text", "text": "pong"}]}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, body=json)
            return FakeResponse()

    class FakeSlot:
        def __init__(self, _kind):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(text_model.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(text_model, "model_slot", FakeSlot)

    result = asyncio.run(text_model.chat_completion("ping"))

    assert result == "pong"
    assert captured["url"] == "https://gateway.example.com/v1/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-test"


def test_kimi_k3_omits_unsupported_temperature(monkeypatch) -> None:
    # DashScope rejects ``temperature`` for kimi-k3; the OpenAI-compatible
    # request body must omit the field entirely.
    _patch_config(monkeypatch, protocol="DashScope（百炼）", api_key="test-key")
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_model_name",
        lambda: "kimi-k3",
    )
    captured: dict = {}
    _fake_httpx(monkeypatch, captured)

    assert asyncio.run(text_model.chat_completion("Hello")) == "pong"
    assert "temperature" not in captured["body"]


def test_unsupported_temperature_learns_and_retries_without_it(
    monkeypatch,
) -> None:
    # A model this build has never seen may still reject ``temperature``. The
    # OpenAI-compatible path must learn the refusal, drop the field, and
    # re-issue the same turn so the caller never sees the failure; the next
    # call then omits it up front.
    from models import config as model_config
    from models.model_capability_cache import get_capability_cache

    _patch_config(monkeypatch, protocol="DashScope（百炼）", api_key="test-key")
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_model_name",
        lambda: "brand-new-model",
    )
    cache = get_capability_cache()
    key = model_config._temperature_capability_key("brand-new-model")
    cache.clear(key)

    bodies: list[dict] = []
    ok_payload = json_module.dumps(
        {"choices": [{"message": {"content": "pong"}}]},
    )

    class FakeResponse:
        headers = {"content-type": "application/json"}

        def __init__(self, status_code: int, text: str) -> None:
            self.status_code = status_code
            self.text = text

        def json(self) -> dict:
            return json_module.loads(self.text)

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, *, headers, json):
            assert url == "https://gateway.example.com/v1/chat/completions"
            assert headers["Authorization"] == "Bearer test-key"
            bodies.append(dict(json))
            if len(bodies) == 1:
                return FakeResponse(
                    400,
                    "Parameter 'temperature'=0.2 is not supported for "
                    "brand-new-model",
                )
            return FakeResponse(200, ok_payload)

    class FakeSlot:
        def __init__(self, _kind):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(text_model.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(text_model, "model_slot", FakeSlot)

    try:
        assert asyncio.run(text_model.chat_completion("Hello")) == "pong"
        # First attempt carried temperature and was rejected; the retry
        # omitted it and succeeded.
        assert "temperature" in bodies[0]
        assert "temperature" not in bodies[1]
        # The refusal is now cached, so later calls omit it without a probe.
        assert model_config.chat_temperature("brand-new-model", 0.2) is None
    finally:
        cache.clear(key)

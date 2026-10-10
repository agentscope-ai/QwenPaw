# -*- coding: utf-8 -*-
"""Text model protocol dispatch and keyless free-tier support."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio

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

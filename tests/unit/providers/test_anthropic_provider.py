# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import copaw.providers.anthropic_provider as anthropic_provider_module
from copaw.providers.anthropic_provider import AnthropicProvider


def _make_provider() -> AnthropicProvider:
    return AnthropicProvider(
        id="anthropic",
        name="Anthropic",
        base_url="https://mock-anthropic.local",
        api_key="ant-test",
        chat_model="AnthropicChatModel",
    )


async def test_check_connection_success(monkeypatch) -> None:
    provider = _make_provider()
    called = {"count": 0}

    class FakeModels:
        async def list(self):
            called["count"] += 1
            return SimpleNamespace(data=[])

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=2.0)

    assert ok is True
    assert msg == ""
    assert called["count"] == 1


async def test_check_connection_api_error_returns_false(monkeypatch) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            raise RuntimeError("boom")

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)
    monkeypatch.setattr(
        anthropic_provider_module.anthropic,
        "APIError",
        Exception,
    )

    ok, msg = await provider.check_connection(timeout=1.0)

    assert ok is False
    assert msg == "Anthropic API error"


async def test_list_model_normalizes_and_deduplicates(monkeypatch) -> None:
    provider = _make_provider()
    rows = [
        SimpleNamespace(id="claude-3-5-haiku", display_name="Claude Haiku"),
        SimpleNamespace(id="claude-3-5-haiku", display_name=""),
        SimpleNamespace(id="claude-3-5-sonnet", display_name=""),
        SimpleNamespace(id="    ", display_name="invalid"),
    ]

    class FakeModels:
        async def list(self):
            return SimpleNamespace(data=rows)

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    models = await provider.fetch_models(timeout=3.0)

    assert [model.id for model in models] == [
        "claude-3-5-haiku",
        "claude-3-5-sonnet",
    ]
    assert [model.name for model in models] == [
        "Claude Haiku",
        "claude-3-5-sonnet",
    ]
    assert provider.models == []


async def test_check_model_connection_success(monkeypatch) -> None:
    provider = _make_provider()
    captured: list[dict] = []

    class FakeStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeMessages:
        async def create(self, **kwargs):
            captured.append(kwargs)
            return FakeStream()

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_model_connection(
        "claude-3-5-haiku",
        timeout=4.0,
    )

    assert ok is True
    assert msg == ""
    assert len(captured) == 1
    assert captured[0]["model"] == "claude-3-5-haiku"
    assert captured[0]["max_tokens"] == 1
    assert captured[0]["messages"] == [{"role": "user", "content": "ping"}]
    assert captured[0]["stream"] is True


async def test_check_model_connection_empty_model_id_returns_false() -> None:
    provider = _make_provider()

    ok, msg = await provider.check_model_connection("   ", timeout=4.0)

    assert ok is False
    assert msg == "Empty model ID"


async def test_check_model_connection_api_error_returns_false(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeMessages:
        async def create(self, **kwargs):
            _ = kwargs
            raise RuntimeError("failed")

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)
    monkeypatch.setattr(
        anthropic_provider_module.anthropic,
        "APIError",
        Exception,
    )

    ok, msg = await provider.check_model_connection(
        "claude-3-5-haiku",
        timeout=4.0,
    )

    assert ok is False
    assert msg == "Model 'claude-3-5-haiku' is not reachable or usable"


async def test_update_config_updates_only_non_none_values() -> None:
    provider = _make_provider()

    provider.update_config(
        {
            "name": "Anthropic Custom",
            "base_url": "https://new.example",
            "api_key": "ant-new",
            "chat_model": "AnthropicChatModel",
            "api_key_prefix": "sk-ant-",
        },
    )

    assert provider.name == "Anthropic Custom"
    assert provider.base_url == "https://new.example"
    assert provider.api_key == "ant-new"
    assert provider.chat_model == "AnthropicChatModel"
    assert provider.api_key_prefix == "sk-ant-"

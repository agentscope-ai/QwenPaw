# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import time
from types import SimpleNamespace

import qwenpaw.providers.anthropic_provider as anthropic_provider_module
from qwenpaw.providers.anthropic_provider import AnthropicProvider


def _make_provider(is_custom: bool = False) -> AnthropicProvider:
    return AnthropicProvider(
        id="anthropic",
        name="Anthropic",
        base_url="https://mock-anthropic.local",
        api_key="ant-test",
        chat_model="AnthropicChatModel",
        is_custom=is_custom,
    )


def test_get_chat_model_instance_uses_configured_max_tokens(
    monkeypatch,
) -> None:
    """Verify that provider-level max_tokens is forwarded to the model."""
    captured: list[dict] = []

    class FakeCompat:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(
        anthropic_provider_module,
        "_AnthropicChatModelCompat",
        FakeCompat,
    )

    provider = _make_provider()
    provider.generate_kwargs = {
        "max_tokens": 4096,
        "temperature": 0.2,
    }

    provider.get_chat_model_instance("claude-3-5-sonnet")

    assert captured[0]["model"] == "claude-3-5-sonnet"
    assert captured[0]["parameters"].max_tokens == 4096


def test_get_chat_model_instance_uses_default_max_tokens_when_unset(
    monkeypatch,
) -> None:
    captured: list[dict] = []

    class FakeCompat:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(
        anthropic_provider_module,
        "_AnthropicChatModelCompat",
        FakeCompat,
    )

    provider = _make_provider()
    provider.get_chat_model_instance("claude-3-5-sonnet")

    assert captured[0]["model"] == "claude-3-5-sonnet"
    assert captured[0]["parameters"].max_tokens == 16384


def test_get_chat_model_instance_does_not_mutate_generate_kwargs(
    monkeypatch,
) -> None:
    captured: list[dict] = []

    class FakeCompat:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(
        anthropic_provider_module,
        "_AnthropicChatModelCompat",
        FakeCompat,
    )

    provider = _make_provider()
    provider.generate_kwargs = {
        "max_tokens": 32768,
        "temperature": 0.2,
    }

    provider.get_chat_model_instance("claude-3-5-sonnet")
    provider.get_chat_model_instance("claude-3-5-sonnet")

    assert [call["parameters"].max_tokens for call in captured] == [
        32768,
        32768,
    ]
    assert provider.generate_kwargs == {
        "max_tokens": 32768,
        "temperature": 0.2,
    }


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
    assert msg == "Anthropic API error: boom"


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
    assert not provider.models


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
    assert captured[0]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "ping"}]},
    ]
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
    provider = _make_provider(is_custom=True)

    provider.update_config(
        {
            "name": "Anthropic Custom",
            "base_url": "https://new.example",
            "api_key": "sk-ant-new",
            "chat_model": "AnthropicChatModel",
            "api_key_prefix": "sk-ant-",
        },
    )

    assert provider.name == "Anthropic Custom"
    assert provider.base_url == "https://new.example"
    assert provider.api_key == "sk-ant-new"
    assert provider.chat_model == "AnthropicChatModel"
    assert provider.api_key_prefix == "sk-ant-"

    provider_info = await provider.get_info()

    assert provider_info.name == "Anthropic Custom"
    assert provider_info.base_url == "https://new.example"
    assert provider_info.api_key == "sk-ant-******"
    assert provider_info.chat_model == "AnthropicChatModel"
    assert provider_info.api_key_prefix == "sk-ant-"
    assert provider_info.is_custom
    assert not provider_info.support_connection_check


# ---------------------------------------- _try_video_source


def _make_text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _make_thinking_block(text: str):
    return SimpleNamespace(type="thinking", thinking=text)


def _make_response(*blocks):
    return SimpleNamespace(content=list(blocks))


async def test_try_video_source_color_match(monkeypatch) -> None:
    provider = _make_provider()
    resp = _make_response(_make_text_block("blue"))

    class FakeMessages:
        async def create(self, **kwargs):
            _ = kwargs
            return resp

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(
        provider,
        "_client",
        lambda timeout=30: fake_client,
    )

    result = await provider._try_video_source(
        "test-model",
        {"type": "base64", "media_type": "video/mp4", "data": "AA=="},
        timeout=30,
        start_time=time.monotonic(),
    )
    assert result is not None
    ok, msg = result
    assert ok is True
    assert "Video supported" in msg


async def test_try_video_source_thinking_block_match(
    monkeypatch,
) -> None:
    provider = _make_provider()
    resp = _make_response(
        _make_thinking_block("The video shows a blue color"),
        _make_text_block("unknown"),
    )

    class FakeMessages:
        async def create(self, **kwargs):
            _ = kwargs
            return resp

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(
        provider,
        "_client",
        lambda timeout=30: fake_client,
    )

    result = await provider._try_video_source(
        "test-model",
        {"type": "base64", "media_type": "video/mp4", "data": "AA=="},
        timeout=30,
        start_time=time.monotonic(),
    )
    assert result is not None
    ok, _ = result
    assert ok is True


async def test_try_video_source_no_match(monkeypatch) -> None:
    provider = _make_provider()
    resp = _make_response(_make_text_block("green"))

    class FakeMessages:
        async def create(self, **kwargs):
            _ = kwargs
            return resp

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(
        provider,
        "_client",
        lambda timeout=30: fake_client,
    )

    result = await provider._try_video_source(
        "test-model",
        {"type": "base64", "media_type": "video/mp4", "data": "AA=="},
        timeout=30,
        start_time=time.monotonic(),
    )
    assert result is not None
    ok, msg = result
    assert ok is False
    assert "did not recognise" in msg


async def test_try_video_source_400_returns_none(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class Fake400Error(
        anthropic_provider_module.anthropic.APIError,
    ):
        def __init__(self):
            self.status_code = 400
            self.message = "bad"
            self.body = {}

    class FakeMessages:
        async def create(self, **kwargs):
            _ = kwargs
            raise Fake400Error()

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(
        provider,
        "_client",
        lambda timeout=30: fake_client,
    )

    result = await provider._try_video_source(
        "test-model",
        {"type": "base64", "media_type": "video/mp4", "data": "AA=="},
        timeout=30,
        start_time=time.monotonic(),
    )
    assert result is None


async def test_try_video_source_http_fallback_accepts_any_answer(
    monkeypatch,
) -> None:
    provider = _make_provider()
    resp = _make_response(_make_text_block("green"))

    class FakeMessages:
        async def create(self, **kwargs):
            _ = kwargs
            return resp

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(
        provider,
        "_client",
        lambda timeout=30: fake_client,
    )

    result = await provider._try_video_source(
        "test-model",
        {"type": "url", "url": "https://example.com/v.mp4"},
        timeout=30,
        start_time=time.monotonic(),
        is_http=True,
    )
    assert result is not None
    ok, _ = result
    assert ok is True

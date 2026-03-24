# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import copaw.providers.anthropic_provider as anthropic_provider_module
from copaw.providers.anthropic_provider import AnthropicProvider


def _make_provider(is_custom: bool = False) -> AnthropicProvider:
    return AnthropicProvider(
        id="anthropic",
        name="Anthropic",
        base_url="https://mock-anthropic.local",
        api_key="ant-test",
        chat_model="AnthropicChatModel",
        is_custom=is_custom,
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


# ---------------------------------------------------------------------------
# probe_model_multimodal tests
# ---------------------------------------------------------------------------


class _FakeStream:
    """Minimal async iterator that yields one chunk then stops."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


async def test_probe_model_multimodal_image_supported(monkeypatch) -> None:
    """Image probe returns supports_image=True."""
    provider = _make_provider()

    class FakeMessages:
        async def create(self, **_kwargs):
            return _FakeStream()

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    result = await provider.probe_model_multimodal("claude-3-5-sonnet")

    assert result.supports_image is True
    assert result.supports_video is False
    assert result.supports_multimodal is True
    assert "Image supported" in result.image_message
    assert "Video not supported" in result.video_message


async def test_probe_model_multimodal_400_returns_false(monkeypatch) -> None:
    """When the model returns a 400 APIError, supports_image is False."""
    provider = _make_provider()

    class FakeMessages:
        async def create(self, **kwargs):
            raise RuntimeError("image is not supported")

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)
    monkeypatch.setattr(
        anthropic_provider_module.anthropic,
        "APIError",
        Exception,
    )

    result = await provider.probe_model_multimodal("claude-text-only")

    assert result.supports_image is False
    assert result.supports_video is False
    assert result.supports_multimodal is False


async def test_probe_model_multimodal_timeout_returns_false(
    monkeypatch,
) -> None:
    """Timeout during probe returns safe default (False)."""
    provider = _make_provider()

    class FakeMessages:
        async def create(self, **kwargs):
            raise TimeoutError("Connection timed out")

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    result = await provider.probe_model_multimodal("slow-model")

    assert result.supports_image is False
    assert result.supports_video is False
    assert result.supports_multimodal is False
    assert "failed" in result.image_message.lower()


async def test_probe_sends_anthropic_image_format(monkeypatch) -> None:
    """Verify the probe sends the correct Anthropic base64 image format."""
    provider = _make_provider()
    captured: list[dict] = []

    class FakeMessages:
        async def create(self, **kwargs):
            captured.append(kwargs)
            return _FakeStream()

    fake_client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    await provider.probe_model_multimodal("claude-3-5-sonnet")

    assert len(captured) == 1
    call = captured[0]
    assert call["model"] == "claude-3-5-sonnet"
    assert call["max_tokens"] == 1
    assert call["stream"] is True

    messages = call["messages"]
    assert len(messages) == 1
    content = messages[0]["content"]
    assert len(content) == 2

    image_block = content[0]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"
    assert len(image_block["source"]["data"]) > 0

    text_block = content[1]
    assert text_block["type"] == "text"
    assert text_block["text"] == "hi"

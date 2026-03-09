# -*- coding: utf-8 -*-
from __future__ import annotations

from copaw.providers.provider import ModelInfo, DefaultProvider


def _make_provider() -> DefaultProvider:
    return DefaultProvider(
        id="default",
        name="Default",
    )


async def test_check_connection() -> None:
    provider = _make_provider()
    ok = await provider.check_connection(timeout=1.0)
    assert ok is False
    provider.models.append(ModelInfo(id="gpt-3.5-turbo", name="gpt-3.5-turbo"))
    ok = await provider.check_connection(timeout=1.0)
    assert ok is True
    ok = await provider.check_model_connection("gpt-3.5-turbo", timeout=1.0)
    assert ok is True
    ok = await provider.check_model_connection(
        "nonexistent-model",
        timeout=1.0,
    )
    assert ok is False


async def test_chat_model() -> None:
    from agentscope.model import OpenAIChatModel, AnthropicChatModel

    provider = _make_provider()
    chat_model_cls = provider.get_chat_model_cls()
    assert chat_model_cls == OpenAIChatModel
    provider.chat_model = "AnthropicChatModel"
    chat_model_cls = provider.get_chat_model_cls()
    assert chat_model_cls == AnthropicChatModel
    provider.chat_model = "NonExistentChatModel"
    try:
        provider.get_chat_model_cls()
        assert False, "Expected ValueError for non-existent chat model"
    except ValueError:
        pass

# -*- coding: utf-8 -*-
"""Tests for active-model context-window metadata."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.routers import providers
from qwenpaw.app.routers.providers import _active_models_info
from qwenpaw.config.config import ModelSlotConfig


def test_active_models_info_uses_runtime_context_resolution():
    provider = SimpleNamespace(get_context_size=lambda _model_id: 1_000_000)
    manager = SimpleNamespace(get_provider=lambda _provider_id: provider)
    slot = ModelSlotConfig(provider_id="dashscope", model="qwen3.7-max")

    info = _active_models_info(manager, slot)

    assert info.active_llm == slot
    assert info.effective_max_input_length == 1_000_000


@pytest.mark.asyncio
async def test_effective_model_reads_chat_runtime_context(monkeypatch):
    session_slot = ModelSlotConfig(provider_id="openai", model="gpt-4o")
    chat = SimpleNamespace(
        meta={
            "runtime_context": {
                "model_slot_override": session_slot.model_dump(),
            },
        },
    )
    workspace = SimpleNamespace(
        agent_id="agent-1",
        chat_manager=SimpleNamespace(get_chat=AsyncMock(return_value=chat)),
    )
    manager = SimpleNamespace(
        get_active_model=lambda: ModelSlotConfig(
            provider_id="global",
            model="default",
        ),
        get_provider=lambda _provider_id: None,
    )
    monkeypatch.setattr(
        providers,
        "get_agent_for_request",
        AsyncMock(return_value=workspace),
    )
    monkeypatch.setattr(
        providers,
        "load_agent_config_async",
        AsyncMock(
            return_value=SimpleNamespace(
                active_model=ModelSlotConfig(
                    provider_id="agent",
                    model="default",
                ),
            ),
        ),
    )
    request = SimpleNamespace(headers={"X-Chat-Id": "chat-1"})

    info = await providers.get_active_models(
        request=request,
        manager=manager,
        scope="effective",
        agent_id="agent-1",
    )

    assert info.active_llm == session_slot
    workspace.chat_manager.get_chat.assert_awaited_once_with("chat-1")

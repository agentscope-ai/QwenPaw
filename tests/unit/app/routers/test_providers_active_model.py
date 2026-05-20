# -*- coding: utf-8 -*-

import pytest

from qwenpaw.app.routers import providers as providers_router
from qwenpaw.config.config import ModelSlotConfig


class DummyProviderManager:
    def __init__(self) -> None:
        self.active_model = ModelSlotConfig(
            provider_id="global",
            model="global-model",
        )

    def get_active_model(self) -> ModelSlotConfig | None:
        return self.active_model


@pytest.mark.asyncio
async def test_get_active_models_effective_returns_global_routed_slot(
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.agents.routing_chat_model.resolve_effective_model_slot",
        lambda _agent_id=None: ModelSlotConfig(
            provider_id="local",
            model="local-model",
        ),
    )

    result = await providers_router.get_active_models(
        request=None,
        manager=DummyProviderManager(),
        scope="effective",
        agent_id="agent-1",
    )

    assert result.active_llm == ModelSlotConfig(
        provider_id="local",
        model="local-model",
    )


@pytest.mark.asyncio
async def test_effective_returns_agent_model_when_routing_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.agents.routing_chat_model.resolve_effective_model_slot",
        lambda _agent_id=None: ModelSlotConfig(
            provider_id="agent",
            model="agent-model",
        ),
    )

    result = await providers_router.get_active_models(
        request=None,
        manager=DummyProviderManager(),
        scope="effective",
        agent_id="agent-1",
    )

    assert result.active_llm == ModelSlotConfig(
        provider_id="agent",
        model="agent-model",
    )


@pytest.mark.asyncio
async def test_get_active_models_effective_returns_agent_routed_slot(
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.agents.routing_chat_model.resolve_effective_model_slot",
        lambda _agent_id=None: ModelSlotConfig(
            provider_id="cloud",
            model="cloud-model",
        ),
    )

    result = await providers_router.get_active_models(
        request=None,
        manager=DummyProviderManager(),
        scope="effective",
        agent_id="agent-1",
    )

    assert result.active_llm == ModelSlotConfig(
        provider_id="cloud",
        model="cloud-model",
    )


@pytest.mark.asyncio
async def test_effective_returns_none_when_routed_slot_unresolved(
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.agents.routing_chat_model.resolve_effective_model_slot",
        lambda _agent_id=None: None,
    )

    result = await providers_router.get_active_models(
        request=None,
        manager=DummyProviderManager(),
        scope="effective",
        agent_id="agent-1",
    )

    assert result.active_llm is None

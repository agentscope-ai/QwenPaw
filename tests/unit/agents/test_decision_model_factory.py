# -*- coding: utf-8 -*-
"""Resolve QwenPaw decision slots into provider-owned AS configuration."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.agents import model_factory as module
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.exceptions import ProviderError
from qwenpaw.providers import ProviderManager
from qwenpaw.providers.typesafe_provider import TypeSafeProvider


@pytest.fixture(name="provider")
def configured_provider(monkeypatch):
    result = TypeSafeProvider(
        id="typesafe",
        name="TypeSafe",
        models=[
            {
                "id": "global-decision",
                "name": "Global",
                "model_type": "decision",
            },
            {
                "id": "agent-decision",
                "name": "Agent",
                "model_type": "decision",
            },
        ],
    )
    monkeypatch.setattr(TypeSafeProvider, "as_decision_model", Mock())
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_slot", [False, True])
async def test_agent_or_global_slot_returns_provider_as_instance(
    monkeypatch,
    provider,
    agent_slot,
):
    config = AgentProfileConfig(id="agent", name="Agent")
    global_slot = ModelSlotConfig(
        provider_id="typesafe",
        model="global-decision",
    )
    slot = (
        ModelSlotConfig(provider_id="typesafe", model="agent-decision")
        if agent_slot
        else global_slot
    )
    if agent_slot:
        config.decision_model = slot
    manager = SimpleNamespace(
        default_models={"decision": global_slot},
        get_provider=lambda _: provider,
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    loop_thread = threading.get_ident()

    def construct(*_args, **_kwargs):
        assert threading.get_ident() != loop_thread
        return provider.as_decision_model.return_value

    provider.as_decision_model.side_effect = construct
    result = await module.create_decision_model_async(config)
    assert result is provider.as_decision_model.return_value
    provider.as_decision_model.assert_called_once_with(
        slot.model,
        timeout=10,
        max_retries=1,
    )


@pytest.mark.asyncio
async def test_missing_decision_selection_does_not_use_chat_model(monkeypatch):
    manager = SimpleNamespace(default_models={"decision": None})
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=ModelSlotConfig(provider_id="chat", model="chat"),
    )
    with pytest.raises(ProviderError, match="decision model"):
        await module.create_decision_model_async(config)


@pytest.mark.asyncio
async def test_cancelled_settings_resolution_never_constructs_client(
    monkeypatch,
    provider,
):
    monkeypatch.setattr(
        module,
        "run_sync_io",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await module.create_decision_model_async(
            AgentProfileConfig(id="agent", name="Agent"),
        )
    provider.as_decision_model.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "disabled", "wrong_type"])
async def test_invalid_decision_provider_never_constructs_client(
    monkeypatch,
    provider,
    failure,
):
    config = AgentProfileConfig(id="agent", name="Agent")
    slot = ModelSlotConfig(provider_id="typesafe", model="global-decision")
    if failure == "disabled":
        provider.enabled = False
    elif failure == "wrong_type":
        provider.models[0].model_type = "chat"
    manager = SimpleNamespace(
        default_models={"decision": slot},
        get_provider=lambda _: None if failure == "missing" else provider,
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    with pytest.raises(ProviderError):
        await module.create_decision_model_async(config)
    provider.as_decision_model.assert_not_called()

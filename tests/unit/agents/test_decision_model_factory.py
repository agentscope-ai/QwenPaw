# -*- coding: utf-8 -*-
"""Decision consumers share QwenPaw's provider configuration."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agentscope import classifier

from qwenpaw.agents.decision_model_factory import create_decision_model
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.exceptions import ProviderError
from qwenpaw.providers import ProviderManager


@pytest.mark.parametrize("agent_slot", [False, True])
def test_decision_slot_credentials_and_model_are_forwarded(
    monkeypatch,
    agent_slot,
):
    config = AgentProfileConfig(id="agent", name="Agent")
    global_slot = ModelSlotConfig(provider_id="typesafe", model="global-jev")
    slot = (
        ModelSlotConfig(provider_id="typesafe", model="agent-jev")
        if agent_slot
        else global_slot
    )
    if agent_slot:
        config.decision_model = slot
    provider = SimpleNamespace(
        enabled=True,
        api_key="host-key",
        base_url="https://example.invalid/v1",
        validate_model_selection=Mock(),
    )
    manager = SimpleNamespace(
        default_models={"decision": global_slot},
        get_provider=Mock(return_value=provider),
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    factory = Mock()
    monkeypatch.setattr(classifier, "JevClassifierModel", factory)
    assert create_decision_model(config) is factory.return_value
    kwargs = factory.call_args.kwargs
    assert kwargs["model"] == slot.model
    assert kwargs["credential"].api_key.get_secret_value() == "host-key"
    assert kwargs["credential"].base_url == provider.base_url
    provider.validate_model_selection.assert_called_once_with(
        slot.model,
        "decision",
    )


def test_missing_decision_selection_does_not_use_chat_model(monkeypatch):
    manager = SimpleNamespace(default_models={"decision": None})
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=ModelSlotConfig(provider_id="chat", model="chat"),
    )
    with pytest.raises(ProviderError, match="decision model"):
        create_decision_model(config)


@pytest.mark.asyncio
async def test_cancelled_settings_resolution_never_constructs_client(
    monkeypatch,
):
    import asyncio
    from unittest.mock import AsyncMock
    from qwenpaw.agents import decision_model_factory as module

    factory = Mock()
    monkeypatch.setattr(classifier, "JevClassifierModel", factory)
    monkeypatch.setattr(
        module,
        "run_sync_io",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await module.create_decision_model_async(
            AgentProfileConfig(id="agent", name="Agent"),
        )
    factory.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    ["missing", "disabled", "no_key", "wrong_type"],
)
def test_invalid_decision_provider_never_constructs_client(
    monkeypatch,
    failure,
):
    config = AgentProfileConfig(id="agent", name="Agent")
    slot = ModelSlotConfig(provider_id="typesafe", model="jev-test")
    provider = SimpleNamespace(
        enabled=failure != "disabled",
        api_key="" if failure == "no_key" else "key",
        base_url="",
        validate_model_selection=Mock(),
    )
    if failure == "wrong_type":
        provider.validate_model_selection.side_effect = ProviderError(
            message="Not a decision model",
        )
    manager = SimpleNamespace(
        default_models={"decision": slot},
        get_provider=Mock(
            return_value=None if failure == "missing" else provider,
        ),
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    factory = Mock()
    monkeypatch.setattr(classifier, "JevClassifierModel", factory)
    with pytest.raises(ProviderError):
        create_decision_model(config)
    factory.assert_not_called()

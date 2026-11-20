# -*- coding: utf-8 -*-
"""Persisted agent models must not stick to a disabled provider."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.exceptions import ProviderError


def _slot(provider_id, model):
    return ModelSlotConfig(provider_id=provider_id, model=model)


def _provider(provider_id, enabled, built):
    """Provider stub that records the model the factory actually builds."""
    provider = Mock(id=provider_id, enabled=enabled)
    model = SimpleNamespace(formatter=SimpleNamespace(), max_retries=0)

    def create(model_id):
        built.append((provider_id, model_id))
        model.identifier = f"{provider_id}/{model_id}"
        return model

    provider.get_chat_model_instance.side_effect = create
    provider.get_model_info.return_value = SimpleNamespace(name=provider_id)
    provider.resolve_model_info.return_value = None
    provider.validate_chat_model.return_value = None
    return provider


def _factory(agent_slot, active_slot, providers, override=None):
    """Call the factory with the agent slot and the global active model."""
    built = []
    by_id = {
        provider_id: _provider(provider_id, enabled, built)
        for provider_id, enabled in providers.items()
    }
    manager = SimpleNamespace(
        get_provider=lambda provider_id: by_id.get(provider_id),
        get_active_model=lambda: active_slot,
    )
    settings = model_factory._AgentModelSettings(model_slot=agent_slot)
    with (
        patch.object(
            model_factory,
            "_load_agent_model_settings",
            return_value=settings,
        ),
        patch.object(
            model_factory.ProviderManager,
            "get_instance",
            return_value=manager,
        ),
        patch.object(model_factory, "_ensure_model_context_size"),
        patch.object(
            model_factory,
            "_install_model_formatter",
            side_effect=lambda model, provider_id=None, **_kwargs: (
                setattr(model, "formatter", provider_id) or provider_id
            ),
        ),
        patch.object(
            model_factory,
            "TokenRecordingModelWrapper",
            side_effect=lambda _provider_id, model, **_kwargs: model,
        ),
        patch.object(
            model_factory,
            "RetryChatModel",
            side_effect=lambda model, **_kwargs: model,
        ),
    ):
        result, _formatter = model_factory.create_model_and_formatter(
            agent_id="default",
            model_slot_override=override,
        )
    return result, built


def test_disabled_agent_model_falls_back_to_global_active_model(caplog):
    """A saved agent.json model on a disabled provider uses the global one."""
    disabled = _slot("kexin_token", "glm-5.3-flash")
    active = _slot("minmax", "MiniMax-M3.1-Flash")

    with caplog.at_level(
        logging.WARNING,
        logger="qwenpaw.agents.model_factory",
    ):
        model, built = _factory(
            disabled,
            active,
            {"kexin_token": False, "minmax": True},
        )

    assert built == [("minmax", "MiniMax-M3.1-Flash")]
    assert model.identifier == "minmax/MiniMax-M3.1-Flash"
    assert "kexin_token" in caplog.text
    assert "minmax:MiniMax-M3.1-Flash" in caplog.text


def test_explicit_disabled_override_does_not_fall_back():
    """A per-request override of a disabled provider is still an error."""
    disabled = _slot("kexin_token", "glm-5.3-flash")
    active = _slot("minmax", "MiniMax-M3.1-Flash")

    with pytest.raises(ProviderError, match="Provider is disabled"):
        _factory(
            _slot("minmax", "MiniMax-M3.1-Flash"),
            active,
            {"kexin_token": False, "minmax": True},
            override=disabled,
        )


@pytest.mark.parametrize(
    "active_slot,providers",
    [
        (None, {"kexin_token": False}),
        (_slot("kexin_token", "glm-5.3-flash"), {"kexin_token": False}),
        (
            _slot("qwen_36", "qwen-plus"),
            {"kexin_token": False, "qwen_36": False},
        ),
        (_slot("minmax", ""), {"kexin_token": False, "minmax": True}),
    ],
)
def test_disabled_agent_model_raises_without_usable_global_model(
    active_slot,
    providers,
):
    """No other enabled global model means the original error still stands."""
    with pytest.raises(ProviderError, match="Provider is disabled"):
        _factory(
            _slot("kexin_token", "glm-5.3-flash"),
            active_slot,
            providers,
        )


def test_enabled_agent_model_is_not_replaced(caplog):
    """An enabled persisted model stays selected and logs no fallback."""
    with caplog.at_level(
        logging.WARNING,
        logger="qwenpaw.agents.model_factory",
    ):
        model, built = _factory(
            _slot("kexin_token", "glm-5.3-flash"),
            _slot("minmax", "MiniMax-M3.1-Flash"),
            {"kexin_token": True, "minmax": True},
        )

    assert built == [("kexin_token", "glm-5.3-flash")]
    assert model.identifier == "kexin_token/glm-5.3-flash"
    assert "falling back" not in caplog.text

# -*- coding: utf-8 -*-
"""Hub is an optional provider, never a personal-model proxy."""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.providers.provider_catalog import (
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
)
from qwenpaw.exceptions import ProviderError
from qwenpaw.providers.hub_managed import managed_slot
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.runtime.builder import AgentBuilder


def test_hub_does_not_choose_a_model_without_user_selection(monkeypatch):
    monkeypatch.setenv(f"QWENPAW_HUB_MODEL_TOKEN", f"token")
    with patch(f"qwenpaw.providers.hub_managed.directory") as directory:
        assert (
            ProviderManager.get_active_model(
                SimpleNamespace(active_model=None),
            )
            is None
        )
        assert managed_slot(None)[0] is None
        with pytest.raises(ProviderError):
            managed_slot(ModelSlotConfig(provider_id=f"kilo", model=f"qwen"))
        directory.assert_not_called()


def test_personal_model_uses_personal_provider_in_hub(monkeypatch):
    monkeypatch.setenv(f"QWENPAW_HUB_MODEL_TOKEN", f"token")
    selected = ModelSlotConfig(provider_id=f"kilo", model=f"qwen")
    provider = Mock(id=f"kilo", enabled=True)
    provider.get_model_info.return_value = SimpleNamespace(name=f"Qwen 27B")
    model = SimpleNamespace()
    provider.get_chat_model_instance.return_value = model
    with (
        patch.object(model_factory, f"_load_agent_model_settings") as settings,
        patch.object(
            model_factory.ProviderManager,
            f"get_instance",
        ) as manager,
        patch.object(model_factory, f"managed_slot") as hub,
        patch.object(model_factory, f"_ensure_model_context_size"),
        patch.object(model_factory, f"_install_model_formatter"),
        patch.object(
            model_factory,
            f"TokenRecordingModelWrapper",
            return_value=model,
        ),
        patch.object(model_factory, f"RetryChatModel", return_value=model),
        patch.object(
            model_factory,
            f"_apply_model_fallbacks",
            return_value=model,
        ),
    ):
        settings.return_value = model_factory._AgentModelSettings()
        manager.return_value.get_provider.return_value = provider
        result, _ = model_factory.create_model_and_formatter(
            agent_id=f"agent",
            model_slot_override=selected,
        )
        manager.return_value.get_provider.assert_called_once_with(f"kilo")
        provider.get_chat_model_instance.assert_called_once_with(f"qwen")
        hub.assert_not_called()
        assert result.display_name == f"Qwen 27B"


@pytest.mark.parametrize(f"name", [f"Qwen 27B", None])
def test_runtime_identity_uses_created_model_not_agent_id(tmp_path, name):
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        session_id=f"s",
        request=None,
        extras={f"active_model_display_name": name},
    )
    config = SimpleNamespace(
        id=f"agent",
        active_model=ModelSlotConfig(
            provider_id=f"hub-managed",
            model=f"opaque-internal-id",
        ),
    )
    prompt = AgentBuilder._build_env_context(ctx, config)
    assert f"opaque-internal-id" not in prompt
    if name:
        assert f"powered by {name}" in prompt
    else:
        assert f"powered by" not in prompt


def test_org_model_keeps_routing_id_and_separate_identity():
    selected = ModelSlotConfig(provider_id=f"hub-managed", model=f"opaque-id")
    provider = Mock()
    provider.get_model_info.return_value = SimpleNamespace(name=f"Org Qwen")
    model = SimpleNamespace()
    provider.get_chat_model_instance.return_value = model
    with (
        patch.object(
            model_factory,
            f"managed_slot",
            return_value=(selected, {}),
        ),
        patch.object(
            model_factory,
            f"managed_provider",
            return_value=provider,
        ),
        patch.object(model_factory, f"_ensure_model_context_size"),
        patch.object(model_factory, f"_install_model_formatter"),
        patch.object(
            model_factory,
            f"TokenRecordingModelWrapper",
            return_value=model,
        ),
    ):
        result, _ = model_factory._create_hub_model_and_formatter(
            model_factory._AgentModelSettings(),
            selected,
            explicit=True,
        )
    provider.get_chat_model_instance.assert_called_once_with(f"opaque-id")
    assert result.display_name == f"Org Qwen"


@pytest.mark.parametrize(f"explicit", [False, True])
@pytest.mark.parametrize(
    (f"level", f"budget", f"expected"),
    [
        (f"high", None, {f"reasoning_effort": f"high"}),
        (
            f"budget",
            4096,
            {f"thinking_enable": True, f"thinking_budget": 4096},
        ),
    ],
)
def test_global_and_explicit_models_apply_identical_thinking(
    monkeypatch,
    explicit,
    level,
    budget,
    expected,
):
    monkeypatch.delenv(f"QWENPAW_HUB_MODEL_TOKEN", raising=False)
    provider = (
        PROVIDER_ANTHROPIC if budget else PROVIDER_OPENAI
    ).configuration_snapshot()
    selected = ModelSlotConfig(
        provider_id=provider.id,
        model=f"claude-sonnet-4-5" if budget else f"gpt-5.2",
    )
    captured = []
    model = SimpleNamespace()

    def create(_provider, model_id):
        captured.append(_provider.get_effective_generate_kwargs(model_id))
        return model

    with (
        patch.object(type(provider), f"get_chat_model_instance", create),
        patch.object(
            model_factory.ProviderManager,
            f"get_instance",
        ) as manager,
        patch.object(model_factory, f"_ensure_model_context_size"),
        patch.object(model_factory, f"_install_model_formatter"),
        patch.object(
            model_factory,
            f"TokenRecordingModelWrapper",
            return_value=model,
        ),
        patch.object(model_factory, f"RetryChatModel", return_value=model),
        patch.object(
            model_factory,
            f"_apply_model_fallbacks",
            return_value=model,
        ),
    ):
        manager.return_value.get_provider.return_value = provider
        manager.return_value.get_active_model.return_value = selected
        config = AgentProfileConfig(
            id=f"test",
            name=f"Test",
            thinking_level=level,
            thinking_budget=budget,
            active_model=selected if explicit else None,
        )
        model_factory.create_model_and_formatter(
            agent_id=f"test",
            agent_config=config,
        )
    for key, value in expected.items():
        assert captured[0][key] == value

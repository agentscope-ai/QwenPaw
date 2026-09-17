# -*- coding: utf-8 -*-
"""Tests for the unified effective chat-model resolver."""

from types import SimpleNamespace

import pytest

from qwenpaw.agents.effective_model import resolve_effective_model
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.exceptions import ProviderError
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.runtime.builder import AgentBuilder


class _Provider:
    def __init__(self, provider_id: str, models: set[str]) -> None:
        self.id = provider_id
        self._models = models

    def has_model(self, model_id: str) -> bool:
        return model_id in self._models


class _ProviderManager:
    def __init__(self, global_slot, providers: dict[str, _Provider]) -> None:
        self._global_slot = global_slot
        self._providers = providers

    def get_active_model(self):
        return self._global_slot

    def get_provider(self, provider_id: str):
        return self._providers.get(provider_id)


def _agent(active_model):
    return SimpleNamespace(active_model=active_model)


def test_explicit_agent_model_wins_over_global() -> None:
    manager = _ProviderManager(
        ModelSlotConfig(provider_id="global", model="gpt-global"),
        {
            "global": _Provider("global", {"gpt-global"}),
            "agent": _Provider("agent", {"gpt-agent"}),
        },
    )

    result = resolve_effective_model(
        _agent(ModelSlotConfig(provider_id="agent", model="gpt-agent")),
        provider_manager=manager,
    )

    assert result == ModelSlotConfig(provider_id="agent", model="gpt-agent")


def test_inherited_agent_uses_current_global_model() -> None:
    manager = _ProviderManager(
        ModelSlotConfig(provider_id="global", model="gpt-global"),
        {"global": _Provider("global", {"gpt-global"})},
    )

    result = resolve_effective_model(_agent(None), provider_manager=manager)

    assert result == ModelSlotConfig(provider_id="global", model="gpt-global")


def test_missing_global_model_returns_actionable_error() -> None:
    manager = _ProviderManager(None, {})

    with pytest.raises(ProviderError, match="No active model configured"):
        resolve_effective_model(_agent(None), provider_manager=manager)


def test_unknown_explicit_provider_or_model_is_rejected() -> None:
    manager = _ProviderManager(
        ModelSlotConfig(provider_id="global", model="gpt-global"),
        {"global": _Provider("global", {"gpt-global"})},
    )

    with pytest.raises(ProviderError, match="Provider 'missing' not found"):
        resolve_effective_model(
            _agent(ModelSlotConfig(provider_id="missing", model="gpt")),
            provider_manager=manager,
        )

    with pytest.raises(ProviderError, match="Model 'missing' not found"):
        resolve_effective_model(
            _agent(ModelSlotConfig(provider_id="global", model="missing")),
            provider_manager=manager,
        )


def test_runtime_environment_uses_inherited_global_model_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _ProviderManager(
        ModelSlotConfig(provider_id="global", model="gpt-global"),
        {"global": _Provider("global", {"gpt-global"})},
    )
    monkeypatch.setattr(
        ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )
    config = SimpleNamespace(
        active_model=None,
        project_dir=None,
        running=SimpleNamespace(shell_command_executable="cmd.exe"),
    )
    context = SimpleNamespace(
        workspace_dir="E:/agent-workspace",
        session_id="session-1",
        request=None,
    )

    result = AgentBuilder._build_env_context(context, config)

    assert "powered by gpt-global" in result

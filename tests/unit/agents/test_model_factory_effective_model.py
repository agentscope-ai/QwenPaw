# -*- coding: utf-8 -*-
"""Integration tests for model_factory effective-model validation."""

from types import SimpleNamespace

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.exceptions import ProviderError


class _UnknownModelProvider:
    id = "cpa"

    @staticmethod
    def has_model(model_id: str) -> bool:
        return False

    @staticmethod
    def get_chat_model_instance(model_id: str):
        raise AssertionError(f"unknown model was instantiated: {model_id}")


class _ProviderManager:
    def get_active_model(self):
        return ModelSlotConfig(provider_id="cpa", model="gpt-5.5")

    def get_provider(self, provider_id: str):
        assert provider_id == "cpa"
        return _UnknownModelProvider()


def test_model_factory_rejects_unknown_effective_model_before_instantiation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = SimpleNamespace(
        llm_retry_enabled=False,
        llm_max_retries=0,
        llm_backoff_base=0.1,
        llm_backoff_cap=1.0,
        llm_max_concurrent=1,
        llm_max_qpm=0,
        llm_rate_limit_pause=0.0,
        llm_rate_limit_jitter=0.0,
        llm_acquire_timeout=1.0,
        light_context_config=SimpleNamespace(
            context_compact_config=SimpleNamespace(enabled=False),
        ),
    )
    agent_config = SimpleNamespace(active_model=None, running=running)
    manager = _ProviderManager()

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: agent_config,
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )

    with pytest.raises(ProviderError, match="Model 'gpt-5.5' not found"):
        model_factory.create_model_and_formatter(agent_id="agent-1")

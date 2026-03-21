# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import copaw.agents.model_factory as model_factory_module
import copaw.config.config as config_module
from copaw.agents.model_factory import create_model_and_formatter
from copaw.config.config import AgentProfileConfig, AgentsRunningConfig
from copaw.providers.retry_chat_model import RetryConfig


def test_create_model_and_formatter_uses_agent_retry_config(monkeypatch):
    fake_model = object()
    captured = {}

    agent_config = AgentProfileConfig(
        id="test-agent",
        name="Test Agent",
        running=AgentsRunningConfig(
            llm_retry_enabled=False,
            llm_max_retries=7,
            llm_backoff_base=0.2,
            llm_backoff_cap=3.5,
        ),
    )

    class FakeRetryChatModel:
        def __init__(self, inner, retry_config=None):
            captured["inner"] = inner
            captured["retry_config"] = retry_config
            self.inner = inner

    class FakeProviderManager:
        def get_active_model(self):
            return SimpleNamespace(provider_id="openai")

    def fake_load_agent_config(agent_id):
        _ = agent_id
        return agent_config

    def fake_get_active_chat_model():
        return fake_model

    def fake_get_instance():
        return FakeProviderManager()

    def fake_create_formatter_instance(chat_model_class):
        _ = chat_model_class
        return "formatter"

    def fake_token_recording_wrapper(provider_id, model):
        return ("token-wrapper", provider_id, model)

    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        fake_load_agent_config,
    )
    monkeypatch.setattr(
        model_factory_module.ProviderManager,
        "get_active_chat_model",
        staticmethod(fake_get_active_chat_model),
    )
    monkeypatch.setattr(
        model_factory_module.ProviderManager,
        "get_instance",
        staticmethod(fake_get_instance),
    )
    monkeypatch.setattr(
        model_factory_module,
        "_create_formatter_instance",
        fake_create_formatter_instance,
    )
    monkeypatch.setattr(
        model_factory_module,
        "TokenRecordingModelWrapper",
        fake_token_recording_wrapper,
    )
    monkeypatch.setattr(
        model_factory_module,
        "RetryChatModel",
        FakeRetryChatModel,
    )

    model, formatter = create_model_and_formatter("test-agent")

    assert formatter == "formatter"
    assert model.inner == ("token-wrapper", "openai", fake_model)
    assert captured["retry_config"] == RetryConfig(
        enabled=False,
        max_retries=7,
        backoff_base=0.2,
        backoff_cap=3.5,
    )

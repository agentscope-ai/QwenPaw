# -*- coding: utf-8 -*-
from types import SimpleNamespace

import pytest
from agentscope.model import OpenAIChatModel

from qwenpaw.agents import model_factory
from qwenpaw.agents.routing_chat_model import RoutingChatModel
import qwenpaw.config.config as config_module
import qwenpaw.config.utils as config_utils
from qwenpaw.config.config import AgentsLLMRoutingConfig
from qwenpaw.providers.models import ModelSlotConfig


class FakeProvider:
    def __init__(self, provider_id: str) -> None:
        self.id = provider_id

    def get_chat_model_cls(self):
        return OpenAIChatModel


class FakeManager:
    def __init__(
        self,
        *,
        providers: dict[str, FakeProvider],
        active_model: ModelSlotConfig | None = None,
    ) -> None:
        self.providers = providers
        self.active_model = active_model

    def get_provider(self, provider_id: str):
        return self.providers.get(provider_id)

    def get_active_model(self) -> ModelSlotConfig | None:
        return self.active_model


class FakeChatModel:
    def __init__(self, provider_id: str, model_name: str):
        self.provider_id = provider_id
        self.model_name = model_name
        self.stream = True

    async def __call__(self, *args, **kwargs):
        return SimpleNamespace(
            provider_id=self.provider_id,
            model_name=self.model_name,
            args=args,
            kwargs=kwargs,
        )


def _patch_config_loaders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_config,
    global_routing_cfg: AgentsLLMRoutingConfig | None = None,
) -> None:
    if global_routing_cfg is None:
        global_routing_cfg = AgentsLLMRoutingConfig(enabled=False)

    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda agent_id: agent_config,
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(llm_routing=global_routing_cfg),
        ),
    )


def _patch_common_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    manager: FakeManager,
) -> list[tuple[str, str]]:
    created: list[tuple[str, str]] = []

    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        lambda: manager,
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_active_chat_model",
        lambda: FakeChatModel("global-provider", "global-model"),
    )
    monkeypatch.setattr(
        model_factory,
        "TokenRecordingModelWrapper",
        lambda provider_id, model: model,
    )
    monkeypatch.setattr(
        model_factory,
        "RetryChatModel",
        lambda model, retry_config=None, rate_limit_config=None: model,
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda chat_model_class: SimpleNamespace(
            formatter_for=chat_model_class.__name__,
        ),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_from_family",
        lambda formatter_family: SimpleNamespace(
            formatter_for=formatter_family.__name__,
        ),
    )

    def fake_create_model_instance_for_provider(
        model_slot: ModelSlotConfig,
        *,
        manager: FakeManager,
    ):
        del manager
        created.append((model_slot.provider_id, model_slot.model))
        return (
            FakeChatModel(
                provider_id=model_slot.provider_id,
                model_name=model_slot.model,
            ),
            OpenAIChatModel,
        )

    monkeypatch.setattr(
        model_factory,
        "_create_model_instance_for_provider",
        fake_create_model_instance_for_provider,
    )
    return created


def _running_config():
    return SimpleNamespace(
        llm_retry_enabled=False,
        llm_max_retries=0,
        llm_backoff_base=0.1,
        llm_backoff_cap=1.0,
        llm_max_concurrent=1,
        llm_max_qpm=0,
        llm_rate_limit_pause=0.0,
        llm_rate_limit_jitter=0.0,
        llm_acquire_timeout=1.0,
    )


def test_routing_uses_agent_active_cloud_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing_cfg = AgentsLLMRoutingConfig(
        enabled=True,
        mode="local_first",
        local=ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b"),
        cloud=None,
    )
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
        llm_routing=routing_cfg,
        running=_running_config(),
    )
    manager = FakeManager(
        providers={
            "ollama": FakeProvider("ollama"),
            "openai": FakeProvider("openai"),
        },
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
    )
    created = _patch_common_mocks(monkeypatch, manager=manager)
    _patch_config_loaders(monkeypatch, agent_config=agent_config)

    model, formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    assert isinstance(model, RoutingChatModel)
    assert model.local_endpoint.provider_id == "ollama"
    assert model.local_endpoint.model_name == "qwen2.5:7b"
    assert model.cloud_endpoint.provider_id == "openai"
    assert model.cloud_endpoint.model_name == "gpt-5"
    assert formatter.formatter_for == "OpenAIChatFormatter"
    assert getattr(formatter, "_qwenpaw_routing_preserve_media", False) is True
    assert created == [
        ("ollama", "qwen2.5:7b"),
        ("openai", "gpt-5"),
    ]


def test_create_model_and_formatter_uses_explicit_cloud_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing_cfg = AgentsLLMRoutingConfig(
        enabled=True,
        mode="cloud_first",
        local=ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b"),
        cloud=ModelSlotConfig(
            provider_id="openai",
            model="gpt-5",
        ),
    )
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b"),
        llm_routing=routing_cfg,
        running=_running_config(),
    )
    manager = FakeManager(
        providers={
            "ollama": FakeProvider("ollama"),
            "openai": FakeProvider("openai"),
        },
        active_model=ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b"),
    )
    created = _patch_common_mocks(monkeypatch, manager=manager)
    _patch_config_loaders(monkeypatch, agent_config=agent_config)

    model, _ = model_factory.create_model_and_formatter(agent_id="agent-1")

    assert isinstance(model, RoutingChatModel)
    assert model.local_endpoint.provider_id == "ollama"
    assert model.cloud_endpoint.provider_id == "openai"
    assert model.routing_cfg.mode == "cloud_first"
    assert created == [
        ("ollama", "qwen2.5:7b"),
        ("openai", "gpt-5"),
    ]


def test_routing_enabled_requires_local_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing_cfg = AgentsLLMRoutingConfig(enabled=True)
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
        llm_routing=routing_cfg,
        running=_running_config(),
    )
    manager = FakeManager(
        providers={"openai": FakeProvider("openai")},
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
    )
    _patch_common_mocks(monkeypatch, manager=manager)
    _patch_config_loaders(monkeypatch, agent_config=agent_config)

    with pytest.raises(ValueError, match="local slot is not configured"):
        model_factory.create_model_and_formatter(agent_id="agent-1")


def test_routing_enabled_requires_resolved_cloud_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing_cfg = AgentsLLMRoutingConfig(
        enabled=True,
        local=ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b"),
    )
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(),
        llm_routing=routing_cfg,
        running=_running_config(),
    )
    manager = FakeManager(
        providers={"ollama": FakeProvider("ollama")},
        active_model=None,
    )
    _patch_common_mocks(monkeypatch, manager=manager)
    _patch_config_loaders(monkeypatch, agent_config=agent_config)

    with pytest.raises(ValueError, match="cloud slot could not be resolved"):
        model_factory.create_model_and_formatter(agent_id="agent-1")


def test_routing_enabled_formatter_mismatch_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LocalFormatter:
        __name__ = "LocalFormatter"

    class CloudFormatter:
        __name__ = "CloudFormatter"

    routing_cfg = AgentsLLMRoutingConfig(
        enabled=True,
        local=ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b"),
        cloud=ModelSlotConfig(provider_id="openai", model="gpt-5"),
    )
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
        llm_routing=routing_cfg,
        running=_running_config(),
    )
    manager = FakeManager(
        providers={
            "ollama": FakeProvider("ollama"),
            "openai": FakeProvider("openai"),
        },
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
    )
    _patch_common_mocks(monkeypatch, manager=manager)
    _patch_config_loaders(monkeypatch, agent_config=agent_config)

    def fake_create_routing_endpoint(
        model_slot,
        manager,
        retry_config=None,
        rate_limit_config=None,
    ):
        del manager, retry_config, rate_limit_config
        return SimpleNamespace(
            provider_id=model_slot.provider_id,
            model_name=model_slot.model,
            formatter_family=(
                LocalFormatter
                if model_slot.provider_id == "ollama"
                else CloudFormatter
            ),
        )

    monkeypatch.setattr(
        model_factory,
        "_create_routing_endpoint",
        fake_create_routing_endpoint,
    )

    with pytest.raises(ValueError, match="same formatter family"):
        model_factory.create_model_and_formatter(agent_id="agent-1")


def test_routing_disabled_uses_manager_active_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing_cfg = AgentsLLMRoutingConfig(enabled=False)
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(),
        llm_routing=routing_cfg,
        running=_running_config(),
    )
    manager = FakeManager(
        providers={"global-provider": FakeProvider("global-provider")},
        active_model=ModelSlotConfig(
            provider_id="global-provider",
            model="global-model",
        ),
    )
    _patch_common_mocks(monkeypatch, manager=manager)
    _patch_config_loaders(monkeypatch, agent_config=agent_config)

    model, formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    assert isinstance(model, FakeChatModel)
    assert model.provider_id == "global-provider"
    assert model.model_name == "global-model"
    assert formatter.formatter_for == "OpenAIChatModel"

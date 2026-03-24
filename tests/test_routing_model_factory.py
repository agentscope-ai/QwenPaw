# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from agentscope.model import OpenAIChatModel

from copaw.agents import model_factory
from copaw.agents.routing_chat_model import RoutingChatModel
import copaw.config.config as config_module
import copaw.config.utils as config_utils
from copaw.config.config import AgentsLLMRoutingConfig
from copaw.providers.models import ModelSlotConfig


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        *,
        is_local: bool = False,
    ) -> None:
        self.id = provider_id
        self.is_local = is_local

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
    def __init__(self, provider_id: str, model_name: str, is_local: bool):
        self.provider_id = provider_id
        self.model_name = model_name
        self.is_local = is_local
        self.stream = True

    async def __call__(self, *args, **kwargs):
        return SimpleNamespace(
            provider_id=self.provider_id,
            model_name=self.model_name,
            is_local=self.is_local,
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
) -> list[tuple[str, str, bool]]:
    created: list[tuple[str, str, bool]] = []

    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        lambda: manager,
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_active_chat_model",
        lambda: (_ for _ in ()).throw(
            AssertionError("active model fallback should not be used"),
        ),
    )
    monkeypatch.setattr(
        model_factory,
        "TokenRecordingModelWrapper",
        lambda provider_id, model: model,
    )
    monkeypatch.setattr(
        model_factory,
        "RetryChatModel",
        lambda model, retry_config=None: model,
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
        provider = manager.get_provider(model_slot.provider_id)
        is_local = bool(provider and provider.is_local)
        created.append((model_slot.provider_id, model_slot.model, is_local))
        return (
            FakeChatModel(
                provider_id=model_slot.provider_id,
                model_name=model_slot.model,
                is_local=is_local,
            ),
            OpenAIChatModel,
        )

    monkeypatch.setattr(
        model_factory,
        "_create_model_instance_for_provider",
        fake_create_model_instance_for_provider,
    )
    return created


def test_routing_uses_agent_active_cloud_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing_cfg = AgentsLLMRoutingConfig(
        enabled=True,
        mode="local_first",
        local=ModelSlotConfig(
            provider_id="llamacpp",
            model="Qwen2.5-0.5B-Instruct-GGUF",
        ),
        cloud=None,
    )
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
        llm_routing=routing_cfg,
        running=SimpleNamespace(
            llm_retry_enabled=False,
            llm_max_retries=0,
            llm_backoff_base=0.1,
            llm_backoff_cap=1.0,
        ),
    )
    manager = FakeManager(
        providers={
            "llamacpp": FakeProvider("llamacpp", is_local=True),
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
    assert model.local_endpoint.provider_id == "llamacpp"
    assert model.local_endpoint.model_name == "Qwen2.5-0.5B-Instruct-GGUF"
    assert model.cloud_endpoint.provider_id == "openai"
    assert model.cloud_endpoint.model_name == "gpt-5"
    assert formatter.formatter_for == "OpenAIChatFormatter"
    assert not created


def test_create_model_and_formatter_uses_explicit_cloud_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing_cfg = AgentsLLMRoutingConfig(
        enabled=True,
        mode="cloud_first",
        local=ModelSlotConfig(provider_id="mlx", model="Qwen3-4B"),
        cloud=ModelSlotConfig(
            provider_id="aliyun-codingplan",
            model="qwen3.5-plus",
        ),
    )
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="mlx", model="Qwen3-4B"),
        llm_routing=routing_cfg,
        running=SimpleNamespace(
            llm_retry_enabled=False,
            llm_max_retries=0,
            llm_backoff_base=0.1,
            llm_backoff_cap=1.0,
        ),
    )
    manager = FakeManager(
        providers={
            "mlx": FakeProvider("mlx", is_local=True),
            "aliyun-codingplan": FakeProvider("aliyun-codingplan"),
        },
        active_model=ModelSlotConfig(provider_id="mlx", model="Qwen3-4B"),
    )
    created = _patch_common_mocks(monkeypatch, manager=manager)
    _patch_config_loaders(monkeypatch, agent_config=agent_config)

    model, _ = model_factory.create_model_and_formatter(agent_id="agent-1")

    assert isinstance(model, RoutingChatModel)
    assert model.local_endpoint.provider_id == "mlx"
    assert model.cloud_endpoint.provider_id == "aliyun-codingplan"
    assert model.routing_cfg.mode == "cloud_first"
    assert not created


def test_routing_enabled_requires_local_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing_cfg = AgentsLLMRoutingConfig(enabled=True)
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
        llm_routing=routing_cfg,
        running=SimpleNamespace(
            llm_retry_enabled=False,
            llm_max_retries=0,
            llm_backoff_base=0.1,
            llm_backoff_cap=1.0,
        ),
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
        local=ModelSlotConfig(provider_id="llamacpp", model="Qwen3-4B"),
        cloud=None,
    )
    agent_config = SimpleNamespace(
        active_model=None,
        llm_routing=routing_cfg,
        running=SimpleNamespace(
            llm_retry_enabled=False,
            llm_max_retries=0,
            llm_backoff_base=0.1,
            llm_backoff_cap=1.0,
        ),
    )
    manager = FakeManager(
        providers={"llamacpp": FakeProvider("llamacpp", is_local=True)},
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
        local=ModelSlotConfig(provider_id="llamacpp", model="Qwen3-4B"),
        cloud=ModelSlotConfig(provider_id="openai", model="gpt-5"),
    )
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
        llm_routing=routing_cfg,
        running=SimpleNamespace(
            llm_retry_enabled=False,
            llm_max_retries=0,
            llm_backoff_base=0.1,
            llm_backoff_cap=1.0,
        ),
    )
    manager = FakeManager(
        providers={
            "llamacpp": FakeProvider("llamacpp", is_local=True),
            "openai": FakeProvider("openai"),
        },
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5"),
    )
    _patch_common_mocks(monkeypatch, manager=manager)
    _patch_config_loaders(monkeypatch, agent_config=agent_config)

    monkeypatch.setattr(
        model_factory,
        "_create_routing_endpoint",
        lambda model_slot, manager, retry_config=None: SimpleNamespace(
            provider_id=model_slot.provider_id,
            model_name=model_slot.model,
            formatter_family=(
                LocalFormatter
                if model_slot.provider_id == "llamacpp"
                else CloudFormatter
            ),
        ),
    )

    with pytest.raises(ValueError, match="same formatter family"):
        model_factory.create_model_and_formatter(agent_id="agent-1")


def test_create_model_and_formatter_logs_agent_config_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = FakeManager(
        providers={"openai": FakeProvider("openai")},
        active_model=ModelSlotConfig(provider_id="openai", model="gpt-5-mini"),
    )
    _patch_common_mocks(monkeypatch, manager=manager)
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda agent_id: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(enabled=False),
            ),
        ),
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_active_chat_model",
        lambda: SimpleNamespace(model_name="gpt-5-mini"),
    )
    warning_mock = MagicMock()
    monkeypatch.setattr(model_factory.logger, "warning", warning_mock)

    model, formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    warning_mock.assert_called_once()
    assert "Failed to load agent config for agent '%s'" in (
        warning_mock.call_args.args[0]
    )
    assert warning_mock.call_args.args[1] == "agent-1"
    assert not isinstance(model, RoutingChatModel)
    assert model.model_name == "gpt-5-mini"
    assert formatter.formatter_for == "OpenAIChatModel"


def test_routing_disabled_uses_manager_active_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing_cfg = AgentsLLMRoutingConfig(enabled=False)
    active_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-5-mini",
    )
    agent_config = SimpleNamespace(
        active_model=None,
        llm_routing=routing_cfg,
        running=SimpleNamespace(
            llm_retry_enabled=False,
            llm_max_retries=0,
            llm_backoff_base=0.1,
            llm_backoff_cap=1.0,
        ),
    )
    manager = FakeManager(
        providers={"openai": FakeProvider("openai")},
        active_model=active_model,
    )
    _patch_common_mocks(monkeypatch, manager=manager)
    _patch_config_loaders(monkeypatch, agent_config=agent_config)
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_active_chat_model",
        lambda: SimpleNamespace(model_name="gpt-5-mini"),
    )

    model, formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    assert not isinstance(model, RoutingChatModel)
    assert model.model_name == "gpt-5-mini"
    assert formatter.formatter_for == "OpenAIChatModel"

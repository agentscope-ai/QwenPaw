# -*- coding: utf-8 -*-
from types import SimpleNamespace

import pytest
from agentscope.model import ChatModelBase

from qwenpaw.agents import model_factory
from qwenpaw.config import config as config_module
from qwenpaw.config import utils as config_utils
from qwenpaw.config.config import AgentsLLMRoutingConfig, ModelSlotConfig


class DummyChatModel(ChatModelBase):
    def __init__(self, model_name: str) -> None:
        super().__init__(model_name=model_name, stream=True)

    async def __call__(self, *args, **kwargs):
        raise NotImplementedError


class DummyProvider:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        return DummyChatModel(f"{self.provider_id}:{model_id}")


class DummyProviderManager:
    def __init__(self) -> None:
        self.providers = {
            "agent": DummyProvider("agent"),
            "local": DummyProvider("local"),
            "global": DummyProvider("global"),
        }
        self.active_model = ModelSlotConfig(
            provider_id="global",
            model="global-model",
        )

    def get_provider(self, provider_id: str):
        return self.providers.get(provider_id)

    def get_active_model(self) -> ModelSlotConfig | None:
        return self.active_model


def build_running_config():
    return SimpleNamespace(
        llm_retry_enabled=False,
        llm_max_retries=1,
        llm_backoff_base=0.1,
        llm_backoff_cap=1.0,
        llm_max_concurrent=1,
        llm_max_qpm=0,
        llm_rate_limit_pause=1.0,
        llm_rate_limit_jitter=0.0,
        llm_acquire_timeout=10.0,
    )


def unwrap_provider_id(
    wrapped_model,
) -> str:
    inner = vars(wrapped_model)["_inner"]
    return vars(inner)["_provider_id"]


def test_factory_uses_global_routing_local_slot(
    monkeypatch,
):
    manager = DummyProviderManager()
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _: "formatter",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(
            active_model=None,
            llm_routing=AgentsLLMRoutingConfig(),
            running=build_running_config(),
        ),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(
                    enabled=True,
                    mode="local_first",
                    local=ModelSlotConfig(
                        provider_id="local",
                        model="local-model",
                    ),
                ),
            ),
        ),
    )

    wrapped_model, formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    assert unwrap_provider_id(wrapped_model) == "local"
    assert formatter == "formatter"


def test_global_routing_does_not_override_agent_model(
    monkeypatch,
):
    manager = DummyProviderManager()
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _: "formatter",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(
            active_model=ModelSlotConfig(
                provider_id="agent",
                model="agent-model",
            ),
            llm_routing=AgentsLLMRoutingConfig(),
            running=build_running_config(),
        ),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(
                    enabled=True,
                    mode="cloud_first",
                    local=ModelSlotConfig(
                        provider_id="local",
                        model="local-model",
                    ),
                    cloud=None,
                ),
            ),
        ),
    )

    wrapped_model, _formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    assert unwrap_provider_id(wrapped_model) == "agent"


def test_global_cloud_without_slot_raises(
    monkeypatch,
):
    manager = DummyProviderManager()
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _: "formatter",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(
            active_model=None,
            llm_routing=AgentsLLMRoutingConfig(),
            running=build_running_config(),
        ),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(
                    enabled=True,
                    mode="cloud_first",
                    local=ModelSlotConfig(
                        provider_id="local",
                        model="local-model",
                    ),
                    cloud=None,
                ),
            ),
        ),
    )

    with pytest.raises(Exception) as exc_info:
        model_factory.create_model_and_formatter(agent_id="agent-1")

    assert "unconfigured slot" in str(exc_info.value)


def test_agent_routing_overrides_agent_model(
    monkeypatch,
):
    manager = DummyProviderManager()
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _: "formatter",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(
            active_model=ModelSlotConfig(
                provider_id="agent",
                model="agent-model",
            ),
            llm_routing=AgentsLLMRoutingConfig(
                enabled=True,
                mode="local_first",
                local=ModelSlotConfig(
                    provider_id="local",
                    model="local-model",
                ),
            ),
            running=build_running_config(),
        ),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(
                    enabled=True,
                    mode="local_first",
                    local=ModelSlotConfig(
                        provider_id="local",
                        model="local-model",
                    ),
                ),
            ),
        ),
    )

    wrapped_model, _formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    assert unwrap_provider_id(wrapped_model) == "local"


def test_agent_cloud_without_slot_raises(
    monkeypatch,
):
    manager = DummyProviderManager()
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _: "formatter",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(
            active_model=ModelSlotConfig(
                provider_id="agent",
                model="agent-model",
            ),
            llm_routing=AgentsLLMRoutingConfig(
                enabled=True,
                mode="cloud_first",
                local=ModelSlotConfig(
                    provider_id="local",
                    model="local-model",
                ),
                cloud=None,
            ),
            running=build_running_config(),
        ),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(
                    enabled=True,
                    mode="local_first",
                    local=ModelSlotConfig(
                        provider_id="global",
                        model="global-local-model",
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(Exception) as exc_info:
        model_factory.create_model_and_formatter(agent_id="agent-1")

    assert "unconfigured slot" in str(exc_info.value)


def test_falls_back_to_global_active_model_when_routing_disabled(
    monkeypatch,
):
    manager = DummyProviderManager()
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _: "formatter",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(
            active_model=None,
            llm_routing=AgentsLLMRoutingConfig(enabled=False),
            running=build_running_config(),
        ),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(
                    enabled=False,
                    mode="local_first",
                    local=ModelSlotConfig(
                        provider_id="local",
                        model="local-model",
                    ),
                ),
            ),
        ),
    )

    wrapped_model, _formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    assert unwrap_provider_id(wrapped_model) == "global"


def test_agent_disabled_routing_override_blocks_global_routing(
    monkeypatch,
):
    manager = DummyProviderManager()
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _: "formatter",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(
            active_model=None,
            llm_routing=AgentsLLMRoutingConfig(
                enabled=False,
                mode="local_first",
                local=ModelSlotConfig(
                    provider_id="local",
                    model="local-model",
                ),
            ),
            running=build_running_config(),
        ),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(
                    enabled=True,
                    mode="local_first",
                    local=ModelSlotConfig(
                        provider_id="local",
                        model="local-model",
                    ),
                ),
            ),
        ),
    )

    wrapped_model, _formatter = model_factory.create_model_and_formatter(
        agent_id="agent-1",
    )

    assert unwrap_provider_id(wrapped_model) == "global"

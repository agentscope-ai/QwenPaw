# -*- coding: utf-8 -*-
from types import SimpleNamespace

import pytest
from agentscope.model import OpenAIChatModel

from copaw.agents import model_factory
from copaw.agents.routing_chat_model import RoutingChatModel
from copaw.config.config import AgentsLLMRoutingConfig
from copaw.providers.models import ModelSlotConfig


class FakeProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        models: list[str],
        is_local: bool = False,
        chat_model_class=OpenAIChatModel,
    ) -> None:
        self.id = provider_id
        self._models = set(models)
        self.is_local = is_local
        self._chat_model_class = chat_model_class

    def has_model(self, model_id: str) -> bool:
        return model_id in self._models

    def get_chat_model_cls(self):
        return self._chat_model_class

    def get_chat_model_instance(self, model_id: str):
        raise NotImplementedError


class FakeManager:
    def __init__(self, providers: dict[str, FakeProvider], active_llm) -> None:
        self._providers = providers
        self._active_llm = active_llm

    def get_provider(self, provider_id: str):
        return self._providers.get(provider_id)

    def get_active_model(self):
        return self._active_llm

    def get_active_chat_model(self):
        raise AssertionError("routing path should be used")


def _patch_common_routing_mocks(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str, bool]]:
    created: list[tuple[str, str, bool]] = []

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

    def fake_create_local_chat_model(*, model_id, **kwargs):
        del kwargs
        created.append(("llamacpp", model_id, True))
        return FakeChatModel("llamacpp", model_id, True)

    def fake_create_formatter_instance(chat_model_class):
        return SimpleNamespace(formatter_for=chat_model_class.__name__)

    def fake_create_formatter_from_family(formatter_family):
        return SimpleNamespace(formatter_for=formatter_family.__name__)

    def fake_get_chat_model_instance(self, model_id: str):
        created.append((self.id, model_id, False))
        return FakeChatModel(self.id, model_id, False)

    monkeypatch.setattr(
        model_factory,
        "create_local_chat_model",
        fake_create_local_chat_model,
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        fake_create_formatter_instance,
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_from_family",
        fake_create_formatter_from_family,
    )
    monkeypatch.setattr(
        FakeProvider,
        "get_chat_model_instance",
        fake_get_chat_model_instance,
        raising=False,
    )
    return created


def _routing_manager(active_llm: ModelSlotConfig) -> FakeManager:
    providers = {
        "llamacpp": FakeProvider(
            provider_id="llamacpp",
            models=["Qwen2.5-0.5B-Instruct-GGUF"],
            is_local=True,
        ),
        "mlx": FakeProvider(
            provider_id="mlx",
            models=["Qwen3-4B"],
            is_local=True,
        ),
        "openai": FakeProvider(
            provider_id="openai",
            models=["gpt-5", "gpt-5-mini"],
        ),
        "aliyun-codingplan": FakeProvider(
            provider_id="aliyun-codingplan",
            models=["qwen3.5-plus"],
        ),
    }
    return FakeManager(providers, active_llm)


def _unwrap_retry_model(model):
    return getattr(model, "_inner", model)


def test_create_model_and_formatter_uses_routing_with_active_cloud_fallback(
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
    created = _patch_common_routing_mocks(monkeypatch)

    monkeypatch.setattr(
        model_factory,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(llm_routing=routing_cfg),
        ),
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(
            lambda: _routing_manager(
                ModelSlotConfig(provider_id="openai", model="gpt-5"),
            ),
        ),
    )

    model, formatter = model_factory.create_model_and_formatter()
    inner_model = _unwrap_retry_model(model)

    assert isinstance(inner_model, RoutingChatModel)
    assert inner_model.local_endpoint.provider_id == "llamacpp"
    assert (
        inner_model.local_endpoint.model_name == "Qwen2.5-0.5B-Instruct-GGUF"
    )
    assert inner_model.cloud_endpoint.provider_id == "openai"
    assert inner_model.cloud_endpoint.model_name == "gpt-5"
    assert formatter.formatter_for == "OpenAIChatFormatter"
    assert not created


@pytest.mark.asyncio
async def test_create_model_and_formatter_loads_only_selected_cloud_route(
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
    created = _patch_common_routing_mocks(monkeypatch)

    monkeypatch.setattr(
        model_factory,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(llm_routing=routing_cfg),
        ),
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(
            lambda: _routing_manager(
                ModelSlotConfig(provider_id="mlx", model="Qwen3-4B"),
            ),
        ),
    )

    model, _ = model_factory.create_model_and_formatter()
    inner_model = _unwrap_retry_model(model)

    assert isinstance(inner_model, RoutingChatModel)
    assert not created

    response = await model(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
    )

    assert response.provider_id == "aliyun-codingplan"
    assert response.model_name == "qwen3.5-plus"
    assert created == [("aliyun-codingplan", "qwen3.5-plus", False)]


@pytest.mark.asyncio
async def test_create_model_and_formatter_loads_local_route_on_first_use(
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
    created = _patch_common_routing_mocks(monkeypatch)

    monkeypatch.setattr(
        model_factory,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(llm_routing=routing_cfg),
        ),
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(
            lambda: _routing_manager(
                ModelSlotConfig(provider_id="openai", model="gpt-5"),
            ),
        ),
    )

    model, _ = model_factory.create_model_and_formatter()
    inner_model = _unwrap_retry_model(model)

    assert isinstance(inner_model, RoutingChatModel)
    assert not created

    response = await model(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
    )

    assert response.provider_id == "llamacpp"
    assert response.model_name == "Qwen2.5-0.5B-Instruct-GGUF"
    assert created == [("llamacpp", "Qwen2.5-0.5B-Instruct-GGUF", True)]


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
    created = _patch_common_routing_mocks(monkeypatch)

    monkeypatch.setattr(
        model_factory,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(llm_routing=routing_cfg),
        ),
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(
            lambda: _routing_manager(
                ModelSlotConfig(provider_id="mlx", model="Qwen3-4B"),
            ),
        ),
    )

    model, _ = model_factory.create_model_and_formatter()
    inner_model = _unwrap_retry_model(model)

    assert isinstance(inner_model, RoutingChatModel)
    assert inner_model.local_endpoint.provider_id == "mlx"
    assert inner_model.cloud_endpoint.provider_id == "aliyun-codingplan"
    assert inner_model.routing_cfg.mode == "cloud_first"
    assert not created

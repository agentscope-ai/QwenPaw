# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from copaw.agents import model_factory
from copaw.agents.routing_chat_model import RoutingChatModel
from copaw.agents.routing_chat_model import RoutingEndpoint
from copaw.agents.routing_chat_model import RoutingPolicy
from copaw.config.config import (
    AgentsLLMRoutingConfig,
)
from copaw.providers.models import ModelSlotConfig
from copaw.providers.models import ResolvedModelConfig


class StubModel:
    def __init__(self, name: str):
        self.name = name
        self.stream = True
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        *,
        messages,
        tools=None,
        tool_choice=None,
        structured_model=None,
        **kwargs,
    ):
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "structured_model": structured_model,
                "kwargs": kwargs,
            },
        )
        return {"model": self.name}


class StubFormatter:
    pass


def _mk_cfg() -> AgentsLLMRoutingConfig:
    cfg = AgentsLLMRoutingConfig(enabled=True)
    cfg.local = ModelSlotConfig(
        provider_id="llamacpp",
        model="local",
    )
    cfg.cloud = ModelSlotConfig(provider_id="openai", model="cloud")
    return cfg


def _mk_endpoint(name: str, model_name: str) -> RoutingEndpoint:
    formatter = StubFormatter()
    return RoutingEndpoint(
        provider_id=name,
        model_name=model_name,
        model=StubModel(model_name),  # type: ignore[arg-type]
        formatter=formatter,  # type: ignore[arg-type]
        formatter_family=StubFormatter,  # type: ignore[arg-type]
    )


def test_routing_policy_local_first_defaults_to_local() -> None:
    cfg = _mk_cfg()
    policy = RoutingPolicy(cfg)

    decision = policy.decide(
        text="hello",
        channel="console",
        tools_available=True,
    )

    assert decision.route == "local"
    assert decision.reasons == ["mode:local_first"]


def test_routing_policy_cloud_first_defaults_to_cloud() -> None:
    cfg = _mk_cfg()
    cfg.mode = "cloud_first"
    policy = RoutingPolicy(cfg)

    decision = policy.decide(
        text="hello",
        channel="console",
        tools_available=True,
    )

    assert decision.route == "cloud"
    assert decision.reasons == ["mode:cloud_first"]


async def test_routing_chat_model_local_first_uses_local_slot() -> None:
    cfg = _mk_cfg()

    local_endpoint = _mk_endpoint("llamacpp", "local")
    cloud_endpoint = _mk_endpoint("openai", "cloud")
    router = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=cfg,
    )

    tools = [{"name": "t"}]
    messages = [{"role": "user", "content": "hello"}]

    out = await router(messages=messages, tools=tools, tool_choice="auto")

    assert out == {"model": "local"}
    local = local_endpoint.model
    cloud = cloud_endpoint.model
    assert len(local.calls) == 1
    assert len(cloud.calls) == 0

    call = local.calls[0]
    assert call["messages"] == messages
    assert call["tools"] == tools
    assert call["tool_choice"] == "auto"


async def test_routing_chat_model_cloud_first_uses_cloud_slot() -> None:
    cfg = _mk_cfg()
    cfg.mode = "cloud_first"

    local_endpoint = _mk_endpoint("llamacpp", "local")
    cloud_endpoint = _mk_endpoint("openai", "cloud")
    router = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=cfg,
    )

    tools = [{"name": "t"}]
    messages = [{"role": "user", "content": "help"}]

    out = await router(messages=messages, tools=tools, tool_choice="auto")

    assert out == {"model": "cloud"}
    local = local_endpoint.model
    cloud = cloud_endpoint.model
    assert len(cloud.calls) == 1
    assert len(local.calls) == 0

    call = cloud.calls[0]
    assert call["messages"] == messages
    assert call["tools"] == tools
    assert call["tool_choice"] == "auto"


def test_create_model_instance_for_provider_uses_slot_provider_id(
    monkeypatch,
) -> None:
    llm_cfg = ResolvedModelConfig(
        model="claude-test",
        base_url="https://api.anthropic.com",
        api_key="key",
        is_local=False,
    )
    seen: dict[str, Any] = {}

    class FakeAnthropicModel:
        pass

    def _fake_get_provider_chat_model(provider_id, providers_data):
        del providers_data
        seen["provider_id"] = provider_id
        return "AnthropicChatModel"

    def _fake_get_chat_model_class(chat_model_name):
        seen["chat_model_name"] = chat_model_name
        return FakeAnthropicModel

    def _fake_create_remote_model_instance(cfg, chat_model_class):
        seen["remote_cfg"] = cfg
        seen["chat_model_class"] = chat_model_class
        return SimpleNamespace(model_name=cfg.model)

    monkeypatch.setattr(
        model_factory,
        "get_provider_chat_model",
        _fake_get_provider_chat_model,
    )
    monkeypatch.setattr(
        model_factory,
        "get_chat_model_class",
        _fake_get_chat_model_class,
    )
    monkeypatch.setattr(
        model_factory,
        "_create_remote_model_instance",
        _fake_create_remote_model_instance,
    )
    (
        model,
        chat_model_class,
    ) = model_factory._create_model_instance_for_provider(
        llm_cfg,
        "anthropic",
        providers_data=SimpleNamespace(),
    )

    assert seen["provider_id"] == "anthropic"
    assert seen["chat_model_name"] == "AnthropicChatModel"
    assert seen["remote_cfg"] is llm_cfg
    assert seen["chat_model_class"] is FakeAnthropicModel
    assert model.model_name == "claude-test"
    assert chat_model_class is FakeAnthropicModel


def test_create_model_and_formatter_with_explicit_cfg_skips_routing(
    monkeypatch,
) -> None:
    llm_cfg = ResolvedModelConfig(model="explicit", is_local=True)
    formatter = StubFormatter()
    seen: dict[str, Any] = {}

    def _unexpected_load_config():
        raise AssertionError("routing should not be initialized")

    def _fake_create_model_instance(cfg):
        seen["llm_cfg"] = cfg
        return StubModel("explicit"), StubModel

    def _fake_create_formatter_instance(chat_model_class):
        seen["chat_model_class"] = chat_model_class
        return formatter

    monkeypatch.setattr(model_factory, "load_config", _unexpected_load_config)
    monkeypatch.setattr(
        model_factory,
        "_create_model_instance",
        _fake_create_model_instance,
    )
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        _fake_create_formatter_instance,
    )

    model, created_formatter = model_factory.create_model_and_formatter(
        llm_cfg
    )

    assert seen["llm_cfg"] is llm_cfg
    assert seen["chat_model_class"] is StubModel
    assert model.name == "explicit"
    assert created_formatter is formatter

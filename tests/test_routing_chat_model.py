# -*- coding: utf-8 -*-
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from copaw.agents.routing_chat_model import RoutingChatModel, RoutingEndpoint
from copaw.config.config import AgentsLLMRoutingConfig


class DummyStructuredOutput(BaseModel):
    value: str


class DummyFormatter:
    pass


class DummyModel:
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


def _endpoint(provider_id: str, model_name: str) -> RoutingEndpoint:
    def _load():
        return DummyModel(provider_id, model_name), DummyFormatter()

    return RoutingEndpoint(
        provider_id=provider_id,
        model_name=model_name,
        formatter_family=DummyFormatter,
        loader=_load,
    )


def _failing_endpoint(provider_id: str, model_name: str) -> RoutingEndpoint:
    def _load():
        raise RuntimeError("load failed")

    return RoutingEndpoint(
        provider_id=provider_id,
        model_name=model_name,
        formatter_family=DummyFormatter,
        loader=_load,
    )


@pytest.mark.asyncio
async def test_default_local_first_uses_local_route() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
    )

    assert response.provider_id == "local-provider"
    assert response.model_name == "local-model"


@pytest.mark.asyncio
async def test_structured_output_forces_cloud_route() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[{"role": "user", "content": "extract a schema"}],
        tools=[],
        structured_model=DummyStructuredOutput,
    )

    assert response.provider_id == "cloud-provider"
    assert response.model_name == "cloud-model"


@pytest.mark.asyncio
async def test_strict_format_prompt_forces_cloud_route() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[
            {
                "role": "user",
                "content": (
                    "Return only a JSON object with keys project and status."
                ),
            },
        ],
        tools=[],
    )

    assert response.provider_id == "cloud-provider"
    assert response.model_name == "cloud-model"


@pytest.mark.asyncio
async def test_freshness_sensitive_prompt_forces_cloud_route() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[
            {
                "role": "user",
                "content": (
                    "Compare the latest prices of AMD and NVDA this week."
                ),
            },
        ],
        tools=[],
    )

    assert response.provider_id == "cloud-provider"
    assert response.model_name == "cloud-model"


@pytest.mark.asyncio
async def test_recent_tool_context_forces_cloud_route() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[
            {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
            {"role": "tool", "content": "tool result"},
        ],
        tools=[],
    )

    assert response.provider_id == "cloud-provider"
    assert response.model_name == "cloud-model"


@pytest.mark.asyncio
async def test_local_load_failure_falls_back_to_cloud() -> None:
    model = RoutingChatModel(
        local_endpoint=_failing_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
    )

    assert response.provider_id == "cloud-provider"
    assert response.model_name == "cloud-model"

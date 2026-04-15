# -*- coding: utf-8 -*-
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from qwenpaw.agents.routing_chat_model import RoutingChatModel, RoutingEndpoint
from qwenpaw.config.config import AgentsLLMRoutingConfig


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
    return RoutingEndpoint(
        provider_id=provider_id,
        model_name=model_name,
        model=DummyModel(provider_id, model_name),
        formatter=DummyFormatter(),
        formatter_family=DummyFormatter,
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
async def test_cloud_first_uses_cloud_route() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="cloud_first"),
    )

    response = await model(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
    )

    assert response.provider_id == "cloud-provider"
    assert response.model_name == "cloud-model"


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
async def test_non_text_user_content_forces_cloud_route() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is in this image"},
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "file:///tmp/demo.png",
                        },
                    },
                ],
            },
        ],
        tools=[],
    )

    assert response.provider_id == "cloud-provider"
    assert response.model_name == "cloud-model"


@pytest.mark.asyncio
async def test_text_blocks_do_not_force_cloud_route() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": "world"},
                ],
            },
        ],
        tools=[],
    )

    assert response.provider_id == "local-provider"
    assert response.model_name == "local-model"


@pytest.mark.asyncio
async def test_required_tool_choice_forces_cloud_route() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[{"role": "user", "content": "use a tool"}],
        tools=[{"name": "search"}],
        tool_choice="required",
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
async def test_old_tool_context_does_not_pin_new_user_turn_to_cloud() -> None:
    model = RoutingChatModel(
        local_endpoint=_endpoint("local-provider", "local-model"),
        cloud_endpoint=_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[
            {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "new question"},
        ],
        tools=[],
    )

    assert response.provider_id == "local-provider"
    assert response.model_name == "local-model"

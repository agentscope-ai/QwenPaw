# -*- coding: utf-8 -*-
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from copaw.agents.routing_chat_model import (
    JUDGE_SYSTEM_PROMPT,
    RoutingChatModel,
    RoutingEndpoint,
    _parse_judge_output,
)
from copaw.config.config import AgentsLLMRoutingConfig


class DummyStructuredOutput(BaseModel):
    value: str


class DummyFormatter:
    pass


def _is_judge_call(messages: list[dict]) -> bool:
    return bool(
        messages
        and messages[0].get("role") == "system"
        and messages[0].get("content") == JUDGE_SYSTEM_PROMPT,
    )


class DummyModel:
    def __init__(
        self,
        provider_id: str,
        model_name: str,
        *,
        judge_outputs: list[str] | None = None,
        judge_error: Exception | None = None,
        response_error: Exception | None = None,
    ):
        self.provider_id = provider_id
        self.model_name = model_name
        self.stream = True
        self.calls: list[dict] = []
        self.judge_outputs = list(
            judge_outputs or ["route=local\nreason=default_local"],
        )
        self.judge_error = judge_error
        self.response_error = response_error

    async def __call__(self, *args, **kwargs):
        messages = kwargs["messages"]
        self.calls.append({"messages": messages, "kwargs": kwargs})

        if _is_judge_call(messages):
            if self.judge_error is not None:
                raise self.judge_error
            judge_output = self.judge_outputs.pop(0)
            return SimpleNamespace(
                provider_id=self.provider_id,
                model_name=self.model_name,
                content=[{"type": "text", "text": judge_output}],
                kwargs=kwargs,
            )

        if self.response_error is not None:
            raise self.response_error

        return SimpleNamespace(
            provider_id=self.provider_id,
            model_name=self.model_name,
            content=[{"type": "text", "text": "ok"}],
            kwargs=kwargs,
        )


def _endpoint(
    provider_id: str,
    model_name: str,
    *,
    model: DummyModel | None = None,
) -> tuple[RoutingEndpoint, DummyModel, dict[str, int]]:
    if model is None:
        model = DummyModel(provider_id, model_name)
    loader_calls = {"count": 0}

    def _load():
        loader_calls["count"] += 1
        return model, DummyFormatter()

    endpoint = RoutingEndpoint(
        provider_id=provider_id,
        model_name=model_name,
        formatter_family=DummyFormatter,
        loader=_load,
    )
    return endpoint, model, loader_calls


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
async def test_judge_selected_local_route_uses_local_model() -> None:
    local_endpoint, local_model, local_loader = _endpoint(
        "local-provider",
        "local-model",
        model=DummyModel(
            "local-provider",
            "local-model",
            judge_outputs=["route=local\nreason=cheap_local"],
        ),
    )
    cloud_endpoint, cloud_model, _ = _endpoint(
        "cloud-provider",
        "cloud-model",
    )
    model = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
    )

    assert response.provider_id == "local-provider"
    assert response.model_name == "local-model"
    assert len(local_model.calls) == 2
    assert len(cloud_model.calls) == 0
    assert local_loader["count"] == 1


@pytest.mark.asyncio
async def test_judge_selected_cloud_route_uses_cloud_model() -> None:
    local_endpoint, local_model, _ = _endpoint(
        "local-provider",
        "local-model",
        model=DummyModel(
            "local-provider",
            "local-model",
            judge_outputs=["route=cloud\nreason=needs_cloud"],
        ),
    )
    cloud_endpoint, cloud_model, _ = _endpoint(
        "cloud-provider",
        "cloud-model",
    )
    model = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    response = await model(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
    )

    assert response.provider_id == "cloud-provider"
    assert response.model_name == "cloud-model"
    assert len(local_model.calls) == 1
    assert len(cloud_model.calls) == 1


@pytest.mark.asyncio
async def test_freshness_signal_uses_latest_user_turn_only() -> None:
    local_endpoint, local_model, _ = _endpoint(
        "local-provider",
        "local-model",
        model=DummyModel(
            "local-provider",
            "local-model",
            judge_outputs=["route=local\nreason=plain_rewrite"],
        ),
    )
    cloud_endpoint, _, _ = _endpoint("cloud-provider", "cloud-model")
    model = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    await model(
        messages=[
            {
                "role": "user",
                "content": "What is the latest AMD stock price today?",
            },
            {"role": "assistant", "content": "It changed recently."},
            {"role": "user", "content": "Rewrite this sentence politely."},
        ],
        tools=[],
    )

    judge_packet = local_model.calls[0]["messages"][-1]["content"]
    assert "freshness_sensitive: False" in judge_packet


@pytest.mark.asyncio
async def test_strict_format_signal_uses_latest_user_turn_only() -> None:
    local_endpoint, local_model, _ = _endpoint(
        "local-provider",
        "local-model",
        model=DummyModel(
            "local-provider",
            "local-model",
            judge_outputs=["route=local\nreason=plain_rewrite"],
        ),
    )
    cloud_endpoint, _, _ = _endpoint("cloud-provider", "cloud-model")
    model = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    await model(
        messages=[
            {
                "role": "user",
                "content": "Return only JSON with keys project and status.",
            },
            {"role": "assistant", "content": "Sure."},
            {
                "role": "user",
                "content": "Summarize this note in one sentence.",
            },
        ],
        tools=[],
    )

    judge_packet = local_model.calls[0]["messages"][-1]["content"]
    assert "strict_format_requested: False" in judge_packet


@pytest.mark.asyncio
async def test_structured_output_flag_is_passed_to_judge_packet() -> None:
    local_endpoint, local_model, _ = _endpoint(
        "local-provider",
        "local-model",
        model=DummyModel(
            "local-provider",
            "local-model",
            judge_outputs=["route=cloud\nreason=structured_output"],
        ),
    )
    cloud_endpoint, _, _ = _endpoint("cloud-provider", "cloud-model")
    model = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    await model(
        messages=[{"role": "user", "content": "extract a schema"}],
        tools=[],
        structured_model=DummyStructuredOutput,
    )

    judge_packet = local_model.calls[0]["messages"][-1]["content"]
    assert "structured_output_requested: True" in judge_packet


@pytest.mark.asyncio
async def test_selected_route_load_failure_raises_runtime_error() -> None:
    local_endpoint, _, _ = _endpoint(
        "local-provider",
        "local-model",
        model=DummyModel(
            "local-provider",
            "local-model",
            judge_outputs=["route=cloud\nreason=needs_cloud"],
        ),
    )
    model = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=_failing_endpoint("cloud-provider", "cloud-model"),
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    with pytest.raises(RuntimeError, match="failed to load"):
        await model(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )


@pytest.mark.asyncio
async def test_selected_route_invoke_failure_raises_runtime_error() -> None:
    local_endpoint, _, _ = _endpoint(
        "local-provider",
        "local-model",
        model=DummyModel(
            "local-provider",
            "local-model",
            judge_outputs=["route=cloud\nreason=needs_cloud"],
        ),
    )
    cloud_endpoint, _, _ = _endpoint(
        "cloud-provider",
        "cloud-model",
        model=DummyModel(
            "cloud-provider",
            "cloud-model",
            response_error=RuntimeError("invoke failed"),
        ),
    )
    model = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    with pytest.raises(RuntimeError, match="invocation failed"):
        await model(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )


@pytest.mark.asyncio
async def test_invalid_judge_payload_raises_runtime_error() -> None:
    local_endpoint, _, _ = _endpoint(
        "local-provider",
        "local-model",
        model=DummyModel(
            "local-provider",
            "local-model",
            judge_outputs=["maybe cloud?"],
        ),
    )
    cloud_endpoint, _, _ = _endpoint("cloud-provider", "cloud-model")
    model = RoutingChatModel(
        local_endpoint=local_endpoint,
        cloud_endpoint=cloud_endpoint,
        routing_cfg=AgentsLLMRoutingConfig(enabled=True, mode="local_first"),
    )

    with pytest.raises(RuntimeError, match="invalid decision payload"):
        await model(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )


def test_parse_judge_output_parses_route_and_reason() -> None:
    decision = _parse_judge_output(
        "route=cloud\nreason=Freshness Sensitive",
        signals=["prompt:freshness_sensitive"],
    )

    assert decision.route == "cloud"
    assert decision.reasons == [
        "prompt:freshness_sensitive",
        "judge:freshness_sensitive",
    ]


def test_parse_judge_output_requires_route_line() -> None:
    with pytest.raises(ValueError, match="valid route line"):
        _parse_judge_output(
            "reason=missing_route",
            signals=[],
        )

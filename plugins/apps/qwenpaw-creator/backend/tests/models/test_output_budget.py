# -*- coding: utf-8 -*-
"""Verify actual provider payloads, including required Anthropic limits."""

import asyncio
import json

import httpx
import pytest

from api.model_routes import ModelConnectionTestRequest, _prepare_probe_payload
from models import config, output_budget, text_model, vlm_model
from utils.exceptions import ModelError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("kind", ["text", "vlm"])
@pytest.mark.parametrize(
    ("protocol", "model", "expected_limit"),
    [
        ("OpenAI", "deepseek-v4.1-flash", None),
        ("DashScope（百炼）", "qwen3.7-plus", None),
        ("Google Gemini", "gemini-2.5-pro", None),
        ("Anthropic Claude", "MiniMax-M2.7", 204800),
    ],
)
def test_model_requests_use_provider_output_budget(
    monkeypatch,
    kind,
    protocol,
    model,
    expected_limit,
):
    for key, value in {
        "api_key": "test-key",
        "base_url": "https://gateway.example",
        "model_name": model,
        "protocol": protocol,
    }.items():
        monkeypatch.setattr(
            config,
            f"get_{kind}_{key}",
            lambda value=value: value,
        )
    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "pong"}}],
                "content": [{"type": "text", "text": "pong"}],
                "candidates": [{"content": {"parts": [{"text": "pong"}]}}],
            },
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(handle),
            **kwargs,
        ),
    )
    client = text_model if kind == "text" else vlm_model
    content = "ping" if kind == "text" else [{"type": "text", "text": "ping"}]
    assert asyncio.run(client.chat_completion(content)) == "pong"
    body = captured[0]
    if expected_limit is None:
        assert "max_tokens" not in body
    else:
        assert body["max_tokens"] == expected_limit
    assert "max_completion_tokens" not in body
    assert "maxOutputTokens" not in body.get("generationConfig", {})


@pytest.mark.parametrize("kind", ["llm", "vlm"])
@pytest.mark.parametrize(
    "protocol",
    ["OpenAI", "Google Gemini", "Anthropic Claude"],
)
def test_connection_probe_follows_same_output_budget(kind, protocol):
    _, _, body = asyncio.run(
        _prepare_probe_payload(
            ModelConnectionTestRequest(
                type=kind,
                protocol=protocol,
                model_name="MiniMax-M2.7",
                base_url="https://gateway.example",
                api_key="test-key",
            ),
        ),
    )
    if protocol == "Anthropic Claude":
        assert body["max_tokens"] == 204800
    else:
        assert "max_tokens" not in body
    assert "maxOutputTokens" not in body.get("generationConfig", {})


def test_claude_dated_alias_reads_sdk_capability():
    from agentscope.model import AnthropicChatModel

    card = next(iter(AnthropicChatModel.list_models()))
    assert (
        output_budget.known_anthropic_output_limit(card.name)
        == card.output_size
    )
    assert (
        output_budget.known_anthropic_output_limit(card.name + "-20260916")
        == card.output_size
    )


@pytest.mark.parametrize("limit", [150000, None, -1, True])
def test_unknown_anthropic_model_uses_models_api_or_reports_missing_capability(
    monkeypatch,
    limit,
):
    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(200, json={"max_tokens": limit})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(handle),
            **kwargs,
        ),
    )
    call = output_budget.anthropic_output_limit(
        "custom-model",
        base_url="https://gateway.example/v1",
        api_key="test-key",
    )
    if limit == 150000:
        assert asyncio.run(call) == limit
    else:
        with pytest.raises(ModelError, match="输出上限") as failed:
            asyncio.run(call)
        assert not failed.value.retryable
    assert captured[0].method == "GET"
    assert (
        str(captured[0].url)
        == "https://gateway.example/v1/models/custom-model"
    )


def test_empty_reasoning_response_preserves_diagnostics_without_reasoning_text(
    monkeypatch,
):
    for key, value in {
        "api_key": "test-key",
        "base_url": "https://gateway.example",
        "model_name": "deepseek-v4.1-flash",
        "protocol": "OpenAI",
    }.items():
        monkeypatch.setattr(
            config,
            f"get_text_{key}",
            lambda value=value: value,
        )
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {
                                    "content": "",
                                    "reasoning_content": "private reasoning",
                                },
                            },
                        ],
                        "usage": {"completion_tokens": 12000},
                    },
                ),
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ModelError) as failed:
        asyncio.run(text_model.chat_completion("generate"))
    assert "length" in str(failed.value)
    assert "12000" in str(failed.value)
    assert "仅返回了推理内容" in str(failed.value)
    assert "private reasoning" not in str(failed.value)

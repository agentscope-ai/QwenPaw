# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Capture the pinned AgentScope file-agent defaults before network I/O."""

import asyncio
import json

try:
    from anthropic._base_client import httpx2 as httpx
except ImportError:
    from anthropic._base_client import httpx
import pytest
from agentscope.model import AnthropicChatModel

from models.output_budget import anthropic_output_limit
from services.file_agent_runtime.model_client import _build_chat_model


@pytest.mark.parametrize("model_id", ["MiniMax-M3.1-Flash", "MiniMax-M3"])
@pytest.mark.parametrize(
    "base_url",
    ["https://api.minimax.io/anthropic", "https://api.minimaxi.com/anthropic"],
)
def test_file_agent_minimax_defaults_use_sdk_protocol(model_id, base_url):
    captured = []

    def respond(request):
        assert str(request.url) == f"{base_url}/v1/messages"
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"",
        )

    async def call():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
        ) as client:
            parameters = AnthropicChatModel.Parameters()
            parameters.max_tokens = await anthropic_output_limit(
                model_id,
                base_url=base_url,
                api_key="test-only",
            )
            model = _build_chat_model(
                api_key="test-only",
                base_url=base_url,
                model_name=model_id,
                protocol="MiniMax",
                parameters=parameters,
                stream=True,
                client_kwargs={"http_client": client},
            )
            response = await model._call_api(model_id, [])
            async for _ in response:
                pass

    asyncio.run(call())
    assert len(captured) == 1
    assert captured[0]["model"] == model_id
    assert captured[0]["max_tokens"] == 524288
    # Omitting thinking uses Flash adaptive / M3 disabled API defaults.
    assert "thinking" not in captured[0]
    assert "output_config" not in captured[0]
    assert "service_tier" not in captured[0]

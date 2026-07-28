# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from agentscope.model import OpenAIResponseModel

from qwenpaw.providers.openai_response_provider import OpenAIResponseProvider


async def test_summary_limit_is_adapted_for_responses_api(
    monkeypatch,
) -> None:
    captured: dict = {}

    async def fake_call_api(self, *args, **kwargs):
        del self, args
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(OpenAIResponseModel, "_call_api", fake_call_api)
    provider = OpenAIResponseProvider(
        id="openai-response",
        name="OpenAI Responses",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        chat_model="OpenAIResponseModel",
    )
    model = provider.get_chat_model_instance("gpt-5")

    result = await model._call_api(
        "gpt-5",
        [],
        max_tokens=256,
        disable_thinking=True,
    )

    assert result == "ok"
    assert captured["max_output_tokens"] == 256
    assert "max_tokens" not in captured

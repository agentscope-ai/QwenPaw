# -*- coding: utf-8 -*-
"""Connectivity probes must stay zero-cost for non-chat models.

Submitting real tasks (ASR/video) as a "ping" is billable and rejected
by the DashScope gateway with 403; probes use free read-only APIs.
"""
from __future__ import annotations

import pytest

from api.model_routes import _probe_payload
from schemas.models import ModelConnectionTestRequest


def _request(**overrides) -> ModelConnectionTestRequest:
    payload = {
        "type": "asr",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "api_key": "sk-test",
        "model_name": "fun-asr",
        "protocol": "DashScope Fun-ASR",
        "provider": "fun-asr",
    }
    payload.update(overrides)
    return ModelConnectionTestRequest(**payload)


@pytest.mark.parametrize(
    ("type_", "model_name", "protocol", "provider"),
    [
        ("asr", "fun-asr", "DashScope Fun-ASR", "fun-asr"),
        ("video", "wan2.7-r2v-flash", "DashScope（百炼）", None),
    ],
)
def test_dashscope_probe_uses_upload_policy(
    type_,
    model_name,
    protocol,
    provider,
) -> None:
    url, headers, payload = _probe_payload(
        _request(
            type=type_,
            model_name=model_name,
            protocol=protocol,
            provider=provider,
        ),
    )

    assert url == "https://dashscope.aliyuncs.com/api/v1/uploads"
    assert payload == {
        "_get_probe": True,
        "action": "getPolicy",
        "model": model_name,
    }
    # Never a billable async task submission.
    assert "X-DashScope-Async" not in headers


def test_token_plan_image_probe_uses_models_endpoint() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="image",
            base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1",
            model_name="wan2.7-image-pro",
            protocol="Aliyun Token Plan",
            provider=None,
        ),
    )

    expected = (
        "https://token-plan.cn-beijing.maas.aliyuncs.com"
        "/compatible-mode/v1/models"
    )
    assert url == expected
    assert payload == {"_get_probe": True}
    assert headers["Authorization"] == "Bearer sk-test"


def test_token_plan_video_probe_uses_models_endpoint() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="video",
            base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1",
            model_name="happyhorse-1.1",
            protocol="Aliyun Token Plan",
            provider=None,
        ),
    )

    expected = (
        "https://token-plan.cn-beijing.maas.aliyuncs.com"
        "/compatible-mode/v1/models"
    )
    assert url == expected
    assert payload == {"_get_probe": True}
    assert headers["Authorization"] == "Bearer sk-test"


def test_llm_probe_still_posts_a_chat_ping() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen-plus",
            protocol="OpenAI 协议",
            provider=None,
        ),
    )

    assert url == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert "_get_probe" not in payload
    assert payload["model"] == "qwen-plus"


def test_anthropic_llm_probe_uses_messages_endpoint() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://api.anthropic.com",
            model_name="claude-sonnet-4-20250514",
            protocol="Anthropic Claude",
            provider=None,
        ),
    )

    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-test"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers
    assert payload["model"] == "claude-sonnet-4-20250514"
    assert payload["max_tokens"] == 8
    assert payload["messages"] == [
        {"role": "user", "content": "Reply with pong only."},
    ]


def test_minimax_llm_probe_uses_anthropic_format() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://api.minimaxi.com/anthropic",
            model_name="MiniMax-M3",
            protocol="MiniMax",
            provider=None,
        ),
    )

    assert url == "https://api.minimaxi.com/anthropic/v1/messages"
    assert headers["x-api-key"] == "sk-test"
    assert payload["model"] == "MiniMax-M3"


def test_gemini_llm_probe_uses_generate_content() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://generativelanguage.googleapis.com",
            model_name="gemini-2.5-pro",
            protocol="Google Gemini",
            provider=None,
        ),
    )

    # Gemini authenticates through the ``key=`` query parameter; a probe
    # without it always fails with 400/401/403.
    assert url == (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/gemini-2.5-pro:generateContent?key=sk-test"
    )
    assert "Authorization" not in headers
    assert payload["contents"] == [
        {"parts": [{"text": "Reply with pong only."}]},
    ]
    assert payload["generationConfig"]["maxOutputTokens"] == 8


def test_gemini_llm_probe_omits_key_when_keyless() -> None:
    url, headers, _payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://generativelanguage.googleapis.com",
            api_key="",
            model_name="gemini-2.5-pro",
            protocol="Google Gemini",
            provider=None,
            require_api_key=False,
        ),
    )

    assert url == (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/gemini-2.5-pro:generateContent"
    )
    assert "Authorization" not in headers


def test_anthropic_llm_probe_omits_key_header_when_keyless() -> None:
    _url, headers, _payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://api.anthropic.com",
            api_key="",
            model_name="claude-sonnet-4-20250514",
            protocol="Anthropic Claude",
            provider=None,
            require_api_key=False,
        ),
    )

    assert "x-api-key" not in headers
    assert "Authorization" not in headers
    assert headers["anthropic-version"] == "2023-06-01"


def test_opencode_keyless_llm_probe_posts_chat_ping_without_auth() -> None:
    # OpenCode Zen serves ``*-free`` models without an API key; the probe
    # must not send an (empty) Authorization header, which the gateway
    # would reject as an invalid key.
    url, headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://opencode.ai/zen/v1",
            api_key="",
            model_name="nemotron-3.5-lightning-free",
            protocol="OpenCode",
            provider=None,
            require_api_key=False,
        ),
    )

    assert url == "https://opencode.ai/zen/v1/chat/completions"
    assert "Authorization" not in headers
    assert payload["model"] == "nemotron-3.5-lightning-free"


def test_anthropic_vlm_probe_converts_image_to_anthropic_format() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="vlm",
            base_url="https://api.anthropic.com",
            model_name="claude-sonnet-4-20250514",
            protocol="Anthropic Claude",
            provider=None,
        ),
    )

    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-test"
    messages = payload["messages"]
    assert len(messages) == 1
    content = messages[0]["content"]
    assert isinstance(content, list)
    text_block = content[0]
    assert text_block["type"] == "text"
    assert text_block["text"] == "Reply with red only."
    image_block = content[1]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"


def test_gemini_vlm_probe_converts_image_to_inline_data() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            type="vlm",
            base_url="https://generativelanguage.googleapis.com",
            model_name="gemini-2.5-pro",
            protocol="Google Gemini",
            provider=None,
        ),
    )

    assert url.endswith(
        "/v1beta/models/gemini-2.5-pro:generateContent?key=sk-test",
    )
    contents = payload["contents"]
    assert len(contents) == 1
    parts = contents[0]["parts"]
    assert len(parts) == 2
    assert parts[0] == {"text": "Reply with red only."}
    assert parts[1]["inline_data"]["mime_type"] == "image/png"

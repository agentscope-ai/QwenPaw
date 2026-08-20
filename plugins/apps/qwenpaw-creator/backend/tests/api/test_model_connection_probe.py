# -*- coding: utf-8 -*-
"""Connectivity probes must stay zero-cost for non-chat models.

Submitting real tasks (ASR transcription, video synthesis) as a
connectivity "ping" is billable and is rejected by the DashScope
gateway with HTTP 403 "current user api does not support asynchronous
calls"; probes therefore use free read-only official APIs instead.
"""
from __future__ import annotations

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


def test_fun_asr_probe_uses_dashscope_upload_policy() -> None:
    url, headers, payload = _probe_payload(_request())

    assert url == "https://dashscope.aliyuncs.com/api/v1/uploads"
    assert payload == {
        "_get_probe": True,
        "action": "getPolicy",
        "model": "fun-asr",
    }
    assert "X-DashScope-Async" not in headers


def test_whisper_probe_reads_model_metadata() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            base_url="https://api.openai.com/v1",
            model_name="whisper-1",
            protocol="OpenAI Whisper",
            provider="whisper",
        ),
    )

    assert url == "https://api.openai.com/v1/models/whisper-1"
    assert payload == {"_get_probe": True}


def test_dashscope_video_probe_uses_upload_policy() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            type="video",
            model_name="wan2.7-r2v-flash",
            protocol="DashScope（百炼）",
            provider=None,
        ),
    )

    assert url == "https://dashscope.aliyuncs.com/api/v1/uploads"
    assert payload["model"] == "wan2.7-r2v-flash"
    assert payload["_get_probe"] is True


def test_volcano_video_probe_lists_tasks_read_only() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            type="video",
            base_url="https://ark.cn-beijing.volces.com",
            model_name="doubao-seedance-2-0",
            protocol="Volcano Engine（火山引擎）",
            provider=None,
        ),
    )

    assert url == (
        "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
    )
    assert payload == {"_get_probe": True, "page_size": 1}


def test_dashscope_image_probe_uses_upload_policy() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            type="image",
            model_name="qwen-image-plus",
            protocol="DashScope（百炼）",
            provider=None,
        ),
    )

    assert url == "https://dashscope.aliyuncs.com/api/v1/uploads"
    assert payload["model"] == "qwen-image-plus"


def test_openai_image_probe_reads_model_metadata() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            type="image",
            base_url="https://api.openai.com/v1",
            model_name="gpt-image-1",
            protocol="OpenAI 协议",
            provider=None,
        ),
    )

    assert url == "https://api.openai.com/v1/models/gpt-image-1"
    assert payload == {"_get_probe": True}


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

    assert url == (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/gemini-2.5-pro:generateContent"
    )
    assert "Authorization" not in headers
    assert payload["contents"] == [
        {"parts": [{"text": "Reply with pong only."}]},
    ]
    assert payload["generationConfig"]["maxOutputTokens"] == 8


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

    assert url.endswith("/v1beta/models/gemini-2.5-pro:generateContent")
    contents = payload["contents"]
    assert len(contents) == 1
    parts = contents[0]["parts"]
    assert len(parts) == 2
    assert parts[0] == {"text": "Reply with red only."}
    assert parts[1]["inline_data"]["mime_type"] == "image/png"

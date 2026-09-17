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

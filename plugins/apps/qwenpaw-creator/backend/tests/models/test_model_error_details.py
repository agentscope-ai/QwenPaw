# -*- coding: utf-8 -*-
"""Model configuration errors must carry diagnosable detail.

User bug reports that only say "model call failed" are not actionable,
so every model-path error names the protocol, model, endpoint (with
credentials redacted), upstream status and a remediation hint.
"""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio

import pytest

from models import text_model, vlm_model
from utils.exceptions import ModelError, redact_url, upstream_status_hint

pytestmark = pytest.mark.unit


def test_redact_url_strips_credential_query_parameters() -> None:
    assert redact_url(
        "https://generativelanguage.googleapis.com/v1beta/models"
        "/m:generateContent?key=sk-secret",
    ) == (
        "https://generativelanguage.googleapis.com/v1beta/models"
        "/m:generateContent"
    )
    assert (
        redact_url("https://gw.example.com/v1?key=sk-x&alt=sse")
        == "https://gw.example.com/v1?alt=sse"
    )
    assert (
        redact_url("https://gw.example.com/v1/chat/completions")
        == "https://gw.example.com/v1/chat/completions"
    )


def test_upstream_status_hint_covers_common_failures() -> None:
    assert "API Key" in upstream_status_hint(401)
    assert "Base URL" in upstream_status_hint(404)
    assert upstream_status_hint(500) == ""


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


def test_text_http_error_includes_context_and_redacts_key() -> None:
    error = text_model._http_error(
        _FakeResponse(401, '{"error": "invalid api key"}'),
        protocol="Google Gemini",
        model_name="gemini-2.5-pro",
        url=(
            "https://generativelanguage.googleapis.com/v1beta/models"
            "/gemini-2.5-pro:generateContent?key=sk-secret"
        ),
    )

    assert isinstance(error, ModelError)
    message = str(error)
    assert "protocol=Google Gemini" in message
    assert "model=gemini-2.5-pro" in message
    assert "HTTP 401" in message
    assert "invalid api key" in message
    assert "鉴权失败" in message
    assert "sk-secret" not in message
    assert not error.retryable


def test_text_http_error_marks_5xx_retryable() -> None:
    error = text_model._http_error(
        _FakeResponse(503, ""),
        protocol="OpenAI-compatible",
        model_name="test-model",
        url="https://gw.example.com/v1/chat/completions",
    )

    assert error.retryable
    assert "上游未返回响应体" in str(error)


def test_text_model_missing_key_error_names_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_api_key",
        lambda: "",
    )
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_model_name",
        lambda: "claude-sonnet",
    )
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_protocol",
        lambda: "Anthropic Claude",
    )
    monkeypatch.setattr(
        text_model.model_config,
        "get_text_base_url",
        lambda: "https://api.anthropic.com",
    )

    with pytest.raises(ModelError) as excinfo:
        asyncio.run(text_model.chat_completion("ping"))

    message = str(excinfo.value)
    assert "Anthropic Claude" in message
    assert "claude-sonnet" in message
    assert "https://api.anthropic.com" in message
    assert not excinfo.value.retryable


def test_vlm_missing_key_error_names_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_api_key",
        lambda: "",
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_base_url",
        lambda: "https://generativelanguage.googleapis.com",
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_model_name",
        lambda: "gemini-2.5-pro",
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_protocol",
        lambda: "Google Gemini",
    )

    with pytest.raises(ModelError) as excinfo:
        asyncio.run(
            vlm_model.chat_completion([{"type": "text", "text": "hi"}]),
        )

    message = str(excinfo.value)
    assert "Google Gemini" in message
    assert "gemini-2.5-pro" in message
    assert "VLM_API_KEY" in message
    assert not excinfo.value.retryable


def test_probe_reports_exactly_which_fields_are_missing(
    monkeypatch,
) -> None:
    from api import model_routes

    class _Item:
        api_key = ""
        base_url = ""
        model_name = ""
        protocol = ""
        provider = None
        voice = ""
        reuse_llm_key = False

    class _Config:
        llm = _Item()
        vlm = _Item()
        asr = _Item()
        tts = _Item()
        s2v = _Item()
        image = _Item()
        video = _Item()
        embedding = _Item()

    monkeypatch.setattr(
        model_routes,
        "load_model_config",
        _Config,
    )
    request = model_routes.ModelConnectionTestRequest(
        type="llm",
        base_url="",
        api_key="",
        model_name="",
        protocol="Anthropic Claude",
        provider=None,
        require_api_key=True,
    )

    response = asyncio.run(model_routes.test_model_connection(request))

    assert not response.ok
    assert "Base URL" in response.error
    assert "API Key" in response.error
    assert "模型名称" in response.error
    assert "Anthropic Claude" in response.error

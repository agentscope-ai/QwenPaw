# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from models import config
from models import image as image_models


def test_generic_qwen_image_env_selects_dashscope_and_is_consumed(
    monkeypatch,
) -> None:
    monkeypatch.delenv("IMAGE_MODEL", raising=False)
    monkeypatch.delenv("DASHSCOPE_IMAGE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_IMAGE_BASE_URL", raising=False)
    monkeypatch.delenv("DASHSCOPE_IMAGE_MODEL_NAME", raising=False)
    monkeypatch.setenv("IMAGE_API_KEY", "generic-image-key")
    monkeypatch.setenv(
        "IMAGE_BASE_URL",
        "https://workspace.example/api/v1/services/aigc/multimodal-generation/generation",
    )
    monkeypatch.setenv("IMAGE_MODEL_NAME", "qwen-image-2.0-pro")
    token = config.set_request_tool_configs({})
    try:
        assert image_models.get_image_backend() == "DASHSCOPE"
        provider = image_models.get_image_model()
        assert provider.api_key == "generic-image-key"
        assert provider.model_name == "qwen-image-2.0-pro"
        assert provider.generation_url.endswith(
            "/multimodal-generation/generation",
        )
    finally:
        config.reset_request_tool_configs(token)


def test_explicit_image_backend_still_wins(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_MODEL", "OPENAI")
    monkeypatch.setenv("IMAGE_MODEL_NAME", "qwen-image-2.0-pro")
    assert image_models.get_image_backend() == "OPENAI"

# -*- coding: utf-8 -*-
from __future__ import annotations

from models import config


def _clear_vlm_env(monkeypatch) -> None:
    for name in (
        "VLM_API_KEY",
        "DASHSCOPE_API_KEY",
        "VLM_BASE_URL",
        "DASHSCOPE_BASE_URL",
        "VLM_MODEL_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_get_user_config", lambda: {})


def test_vlm_defaults_to_the_current_text_credentials_endpoint_and_model(
    monkeypatch,
) -> None:
    _clear_vlm_env(monkeypatch)
    monkeypatch.setattr(config, "get_text_api_key", lambda: "text-key")
    monkeypatch.setattr(
        config,
        "get_text_base_url",
        lambda: "https://private.example/compatible-mode/v1",
    )
    monkeypatch.setattr(config, "get_text_model_name", lambda: "qwen3.7-plus")
    token = config.set_request_tool_configs({})
    try:
        assert config.get_vlm_api_key() == "text-key"
        assert (
            config.get_vlm_base_url()
            == "https://private.example/compatible-mode/v1"
        )
        assert config.get_vlm_model_name() == "qwen3.7-plus"
        assert (
            config.get_vlm_chat_url()
            == "https://private.example/compatible-mode/v1/chat/completions"
        )
    finally:
        config.reset_request_tool_configs(token)


def test_explicit_request_scoped_vlm_config_wins_over_text_fallback(
    monkeypatch,
) -> None:
    _clear_vlm_env(monkeypatch)
    token = config.set_request_tool_configs(
        {
            config.CREATOR_VLM_CONFIG_TOOL: {
                "api_key": "vlm-key",
                "base_url": "https://vlm.example/v1",
                "model": "vlm-model",
            },
        },
    )
    try:
        assert config.get_vlm_api_key() == "vlm-key"
        assert config.get_vlm_base_url() == "https://vlm.example/v1"
        assert config.get_vlm_model_name() == "vlm-model"
    finally:
        config.reset_request_tool_configs(token)

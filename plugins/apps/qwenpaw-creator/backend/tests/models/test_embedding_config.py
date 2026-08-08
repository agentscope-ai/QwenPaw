# -*- coding: utf-8 -*-
"""creator_embedding_model config-tree resolution tests."""
from __future__ import annotations

from models import config


def test_embedding_config_reuses_vlm_key(monkeypatch) -> None:
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.setattr(
        config,
        "_get_user_config",
        lambda: {"embedding": {"enabled": True, "reuse_vlm_key": True}},
    )
    monkeypatch.setattr(config, "get_vlm_api_key", lambda: "vlm-key")
    token = config.set_request_tool_configs({})
    try:
        assert config.is_embedding_enabled()
        assert config.is_embedding_configured()
        assert config.get_embedding_api_key() == "vlm-key"
        assert config.get_embedding_model_name() == "qwen3-vl-embedding"
    finally:
        config.reset_request_tool_configs(token)


def test_embedding_config_disabled_without_reuse(monkeypatch) -> None:
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_ENABLED", raising=False)
    monkeypatch.setattr(
        config,
        "_get_user_config",
        lambda: {"embedding": {"enabled": True, "reuse_vlm_key": False}},
    )
    monkeypatch.setattr(config, "get_vlm_api_key", lambda: "vlm-key")
    token = config.set_request_tool_configs({})
    try:
        assert config.get_embedding_api_key() == ""
        assert not config.is_embedding_configured()
    finally:
        config.reset_request_tool_configs(token)


def test_explicit_embedding_key_wins(monkeypatch) -> None:
    monkeypatch.setattr(
        config,
        "_get_user_config",
        lambda: {
            "embedding": {
                "enabled": True,
                "api_key": "explicit-key",
                "reuse_vlm_key": True,
            },
        },
    )
    monkeypatch.setattr(config, "get_vlm_api_key", lambda: "vlm-key")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    token = config.set_request_tool_configs({})
    try:
        assert config.get_embedding_api_key() == "explicit-key"
    finally:
        config.reset_request_tool_configs(token)

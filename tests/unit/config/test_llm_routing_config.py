# -*- coding: utf-8 -*-
# pylint: disable=missing-function-docstring,no-member
"""Tests for agent LLM routing configuration."""

from qwenpaw.config.config import (
    AgentsLLMFallbackConfig,
    AgentsLLMRoutingConfig,
    ModelSlotConfig,
)


def test_llm_routing_fallback_defaults_are_disabled() -> None:
    cfg = AgentsLLMRoutingConfig()

    assert cfg.fallback.enabled is False
    assert cfg.fallback.models == []


def test_llm_routing_old_payload_without_fallback_still_loads() -> None:
    cfg = AgentsLLMRoutingConfig.model_validate(
        {
            "enabled": True,
            "mode": "local_first",
            "local": {"provider_id": "ollama", "model": "qwen3"},
        },
    )

    assert cfg.enabled is True
    assert cfg.local == ModelSlotConfig(provider_id="ollama", model="qwen3")
    assert cfg.fallback == AgentsLLMFallbackConfig()


def test_llm_routing_fallback_roundtrip() -> None:
    cfg = AgentsLLMRoutingConfig.model_validate(
        {
            "fallback": {
                "enabled": True,
                "models": [
                    {"provider_id": "dashscope", "model": "qwen-plus"},
                    {"provider_id": "deepseek", "model": "deepseek-chat"},
                ],
            },
        },
    )

    dumped = cfg.model_dump(mode="json")

    assert dumped["fallback"] == {
        "enabled": True,
        "models": [
            {"provider_id": "dashscope", "model": "qwen-plus"},
            {"provider_id": "deepseek", "model": "deepseek-chat"},
        ],
    }

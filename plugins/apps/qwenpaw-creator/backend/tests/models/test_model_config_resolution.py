# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Config-tree resolution: env fallbacks, request overrides, turn limits."""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from models import config
from models import image as image_models
from models.config import (
    DEFAULT_MAINLINE_MAX_MODEL_TURNS,
    DEFAULT_SPECIALIST_MAX_MODEL_TURNS,
    get_mainline_max_model_turns,
    get_specialist_max_model_turns,
    scale_mainline_max_model_turns,
)
from models.image.dashscope_provider import DashScopeImageModel
from models.image.openai_provider import OpenAIImageModel


pytestmark = pytest.mark.unit


def _patch_user_config(monkeypatch, data: dict) -> None:
    monkeypatch.setattr(config, "_get_user_config", lambda: data)


@contextmanager
def _tool_configs(configs: dict | None = None):
    token = config.set_request_tool_configs(configs or {})
    try:
        yield
    finally:
        config.reset_request_tool_configs(token)


# ---------------------------------------------------------------------------
# Image backend selection and concurrency
# ---------------------------------------------------------------------------


def test_generic_qwen_image_env_selects_dashscope_and_is_consumed(
    monkeypatch,
) -> None:
    for name in (
        "IMAGE_MODEL",
        "DASHSCOPE_IMAGE_API_KEY",
        "DASHSCOPE_IMAGE_BASE_URL",
        "DASHSCOPE_IMAGE_MODEL_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("IMAGE_API_KEY", "generic-image-key")
    monkeypatch.setenv(
        "IMAGE_BASE_URL",
        "https://workspace.example/api/v1/services/aigc/multimodal-generation/generation",
    )
    monkeypatch.setenv("IMAGE_MODEL_NAME", "qwen-image-2.0-pro")
    with _tool_configs():
        assert image_models.get_image_backend() == "DASHSCOPE"
        provider = image_models.get_image_model()
        assert provider.api_key == "generic-image-key"
        assert provider.model_name == "qwen-image-2.0-pro"
        assert provider.generation_url.endswith(
            "/multimodal-generation/generation",
        )


def test_explicit_image_backend_still_wins(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_MODEL", "OPENAI")
    monkeypatch.setenv("IMAGE_MODEL_NAME", "qwen-image-2.0-pro")
    assert image_models.get_image_backend() == "OPENAI"


def test_unconfigured_concurrency_follows_the_scheduler_dispatch_cap(
    monkeypatch,
) -> None:
    """The provider semaphore must not default below media_parallelism.

    A silent 1-slot default serialized renders behind model_slot("image")
    while the work graph showed parallel RUNNING nodes (field runs
    2026-08-06/07); the fix couples the default to the scheduler's cap.
    """

    for name in (
        "DASHSCOPE_IMAGE_CONCURRENCY",
        "OPENAI_IMAGE_CONCURRENCY",
        "IMAGE_CONCURRENCY",
    ):
        monkeypatch.delenv(name, raising=False)
    expected = config.get_media_parallelism()
    assert expected >= 5  # the new dispatch-cap default
    assert DashScopeImageModel.from_config().concurrency == expected
    assert OpenAIImageModel.from_config().concurrency == expected


# ---------------------------------------------------------------------------
# Video concurrency and endpoint URLs
# ---------------------------------------------------------------------------


def test_unconfigured_video_concurrency_follows_the_scheduler_dispatch_cap(
    monkeypatch,
) -> None:
    """The video semaphore must not default below media_parallelism.

    The old module-level VIDEO_CONCURRENCY snapshot defaulted to 1,
    serializing renders behind model_slot("video") exactly like the
    image 1-slot default did; the fix couples the default to the
    scheduler's cap.
    """

    monkeypatch.delenv("VIDEO_CONCURRENCY", raising=False)
    expected = config.get_media_parallelism()
    assert expected >= 5  # the dispatch-cap default
    assert config.get_video_concurrency() == expected


def test_wan_video_urls_accept_api_root_or_full_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(config, "get_video_backend", lambda: "wan")
    monkeypatch.setattr(
        config,
        "get_video_base_url",
        lambda: "https://workspace.example/api/v1",
    )
    assert (
        config.get_video_submit_url()
        == "https://workspace.example/api/v1/services/aigc/video-generation/video-synthesis"
    )
    assert (
        config.get_video_task_url("task-1")
        == "https://workspace.example/api/v1/tasks/task-1"
    )

    # A fully-qualified submit endpoint must not gain a duplicate path.
    endpoint = "https://workspace.example/api/v1/services/aigc/video-generation/video-synthesis"
    monkeypatch.setattr(config, "get_video_base_url", lambda: endpoint)
    assert config.get_video_submit_url() == endpoint
    assert (
        config.get_video_task_url("task-2")
        == "https://workspace.example/api/v1/tasks/task-2"
    )


def test_video_provider_poll_interval_is_request_configurable() -> None:
    with _tool_configs(
        {config.CREATOR_VIDEO_CONFIG_TOOL: {"poll_interval_seconds": 2.5}},
    ):
        assert config.get_video_poll_interval_seconds() == 2.5


# ---------------------------------------------------------------------------
# VLM falls back to text credentials
# ---------------------------------------------------------------------------


def _clear_vlm_env(monkeypatch) -> None:
    for name in (
        "VLM_API_KEY",
        "DASHSCOPE_API_KEY",
        "VLM_BASE_URL",
        "DASHSCOPE_BASE_URL",
        "VLM_MODEL_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    _patch_user_config(monkeypatch, {})


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
    with _tool_configs():
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


@pytest.mark.parametrize(
    ("protocol", "configured_base_url", "model_name", "expected_url"),
    [
        (
            "Anthropic Claude",
            "https://api.anthropic.com",
            "claude-sonnet-4-20250514",
            "https://api.anthropic.com/v1/messages",
        ),
        (
            "MiniMax",
            "https://api.minimaxi.com/anthropic",
            "MiniMax-M3",
            "https://api.minimaxi.com/anthropic/v1/messages",
        ),
        (
            "Google Gemini",
            "https://generativelanguage.googleapis.com",
            "gemini-2.5-pro",
            "https://generativelanguage.googleapis.com"
            "/v1beta/models/gemini-2.5-pro:generateContent",
        ),
    ],
)
def test_vlm_chat_url_follows_the_inherited_text_protocol(
    monkeypatch,
    protocol,
    configured_base_url,
    model_name,
    expected_url,
) -> None:
    """Anthropic-style protocols post to /v1/messages, Gemini to
    :generateContent — the VLM fallback must inherit that, not assume
    OpenAI's /chat/completions."""
    _clear_vlm_env(monkeypatch)
    monkeypatch.setattr(config, "get_text_api_key", lambda: "text-key")
    monkeypatch.setattr(
        config,
        "get_text_base_url",
        lambda: configured_base_url,
    )
    monkeypatch.setattr(config, "get_text_model_name", lambda: model_name)
    monkeypatch.setattr(config, "get_text_protocol", lambda: protocol)
    with _tool_configs():
        assert config.get_vlm_protocol() == protocol
        assert config.get_vlm_chat_url() == expected_url


# ---------------------------------------------------------------------------
# Agent turn limits
# ---------------------------------------------------------------------------


def test_turn_limits_default_without_config_or_on_invalid_values(
    monkeypatch,
) -> None:
    for data in (
        {},
        {
            "agent_runtime": {
                "mainline_max_model_turns": 0,
                "specialist_max_model_turns": True,
            },
        },
    ):
        _patch_user_config(monkeypatch, data)
        assert (
            get_mainline_max_model_turns() == DEFAULT_MAINLINE_MAX_MODEL_TURNS
        )
        assert (
            get_specialist_max_model_turns()
            == DEFAULT_SPECIALIST_MAX_MODEL_TURNS
        )


def test_turn_budget_scales_with_element_count() -> None:
    # Small projects keep the configured floor.
    assert scale_mainline_max_model_turns(24, 0) == 24
    assert scale_mainline_max_model_turns(24, 5) == 24  # 8 + 15 = 23 < 24
    # Element-heavy projects raise the cap: 8 + 3 * 12 = 44.
    assert scale_mainline_max_model_turns(24, 12) == 44
    # A higher configured value is never lowered.
    assert scale_mainline_max_model_turns(64, 12) == 64
    # Negative counts (defensive) fall back to the base.
    assert scale_mainline_max_model_turns(24, -3) == 24

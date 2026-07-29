# -*- coding: utf-8 -*-
"""Provider configuration and retry policy."""

from __future__ import annotations

import os
import re

import httpx

from models import config as model_config

DEFAULT_VISUAL_SEARCH_PROVIDERS = ("tavily", "dashscope_web_search_image")


def tavily_api_key() -> str:
    return (
        os.environ.get("TAVILY_API_KEY")
        or os.environ.get("WEB_GROUNDING_TAVILY_API_KEY")
        or ""
    )


def dashscope_api_key() -> str:
    try:
        return model_config.get_text_api_key() or os.environ.get(
            "DASHSCOPE_API_KEY",
            "",
        )
    except Exception:
        return os.environ.get("DASHSCOPE_API_KEY", "")


def dashscope_base_url() -> str:
    try:
        return model_config.get_text_base_url()
    except Exception:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"


def dashscope_model() -> str:
    try:
        return model_config.get_text_model_name() or "qwen3.7-plus"
    except Exception:
        return "qwen3.7-plus"


def dashscope_web_search_api_key() -> str:
    """Text web search shares Creator's configured text-model credential."""
    return dashscope_api_key()


def dashscope_web_search_base_url() -> str:
    """Text web search shares Creator's configured text-model endpoint."""
    return dashscope_base_url()


def dashscope_web_search_model() -> str:
    """Text web search shares Creator's configured text model."""
    return dashscope_model()


def responses_url_from_base(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if base.endswith("/responses"):
        return base
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return f"{base}/responses"


def normalize_visual_provider_name(value: str) -> str:
    provider = value.strip().lower().replace("-", "_")
    return {
        "qwen": "dashscope_web_search_image",
        "dashscope": "dashscope_web_search_image",
        "dashscope_image": "dashscope_web_search_image",
        "web_search_image": "dashscope_web_search_image",
        "qwen_web_search_image": "dashscope_web_search_image",
    }.get(provider, provider)


def visual_search_provider_order() -> tuple[str, ...]:
    raw = os.environ.get("WEB_GROUNDING_IMAGE_PROVIDERS") or os.environ.get(
        "WEB_GROUNDING_VISUAL_PROVIDERS",
    )
    if not raw:
        providers: list[str] = []
        if tavily_api_key():
            providers.append("tavily")
        if dashscope_api_key():
            providers.append("dashscope_web_search_image")
        return tuple(providers or DEFAULT_VISUAL_SEARCH_PROVIDERS)

    providers = []
    for item in re.split(r"[,，;；\s]+", raw):
        provider = normalize_visual_provider_name(item)
        if provider and provider not in providers:
            providers.append(provider)
    return tuple(providers or DEFAULT_VISUAL_SEARCH_PROVIDERS)


def visual_search_min_results_for_fallback() -> int:
    raw = os.environ.get("WEB_GROUNDING_IMAGE_MIN_RESULTS_FOR_FALLBACK", "1")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def is_retryable_visual_search_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return (
            exc.response.status_code >= 500 or exc.response.status_code == 429
        )
    return False

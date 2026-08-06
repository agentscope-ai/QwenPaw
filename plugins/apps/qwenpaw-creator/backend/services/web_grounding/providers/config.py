# -*- coding: utf-8 -*-
"""Provider configuration and retry policy."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

from models import config as model_config

DEFAULT_VISUAL_SEARCH_PROVIDERS = (
    "tavily",
    "serper",
    "dashscope_web_search_image",
)
DEFAULT_VISUAL_SEARCH_MIN_RESULTS_FOR_FALLBACK = 2


def tavily_api_key() -> str:
    return model_config.get_web_grounding_tavily_api_key()


def serper_api_key() -> str:
    return model_config.get_web_grounding_serper_api_key()


def dashscope_api_key() -> str:
    try:
        return (
            model_config.get_web_grounding_search_api_key()
            or os.environ.get(
                "DASHSCOPE_API_KEY",
                "",
            )
        )
    except Exception:
        return os.environ.get("DASHSCOPE_API_KEY", "")


def dashscope_base_url() -> str:
    try:
        return model_config.get_web_grounding_search_base_url()
    except Exception:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"


def dashscope_model() -> str:
    try:
        return (
            model_config.get_web_grounding_search_model_name()
            or "qwen3.7-plus"
        )
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


def dashscope_native_search_unavailable_reason(
    *,
    api_key_override: str | None = None,
) -> str:
    """Explain why the DashScope/Qwen native-search adapter cannot run."""

    try:
        if not model_config.get_web_grounding_native_search_enabled():
            return "native_search_disabled"
        provider = model_config.get_web_grounding_search_provider()
        if provider != "dashscope_qwen":
            return f"native_search_provider_unsupported:{provider}"
        api_key = (
            api_key_override
            if api_key_override is not None
            else dashscope_api_key()
        )
        base_url = dashscope_base_url()
        model = dashscope_model()
        if not api_key or not base_url or not model:
            return "native_search_config_incomplete"
        protocol = model_config.get_web_grounding_search_protocol()
        hostname = urlparse(base_url).hostname or ""
        if (
            "dashscope" not in protocol.casefold()
            and "百炼" not in protocol
            and "dashscope" not in hostname.casefold()
        ):
            return "native_search_provider_incompatible"
        return ""
    except Exception:
        return "native_search_config_unavailable"


def responses_url_from_base(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if base.endswith("/responses"):
        return base
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return f"{base}/responses"


def visual_search_provider_order() -> tuple[str, ...]:
    """Return the fixed product provider chain, filtered by availability."""

    native_search_ok = not dashscope_native_search_unavailable_reason()
    available = {
        "tavily": bool(tavily_api_key()),
        "serper": bool(serper_api_key()),
        "dashscope_web_search_image": native_search_ok,
    }
    providers = tuple(
        provider
        for provider in DEFAULT_VISUAL_SEARCH_PROVIDERS
        if available[provider]
    )
    return providers


def visual_search_min_results_for_fallback() -> int:
    return DEFAULT_VISUAL_SEARCH_MIN_RESULTS_FOR_FALLBACK


def is_retryable_visual_search_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return (
            exc.response.status_code >= 500 or exc.response.status_code == 429
        )
    return False

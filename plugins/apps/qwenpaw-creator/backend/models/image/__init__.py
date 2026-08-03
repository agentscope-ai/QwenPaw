# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,too-many-return-statements
"""Image generation providers.

Public API:

    get_image_model() -> BaseImageModel
    generate_image(prompt, aspect_ratio, reference_image_urls) -> str

The provider is selected by ``IMAGE_MODEL`` (DASHSCOPE / OPENAI, see
config.py). Each provider reads its own configuration via its ``from_config()``
classmethod, so adding a new backend means writing one subclass and
registering it in ``_PROVIDERS`` below.
"""

import os
from urllib.parse import urlsplit

from models.image.base import BaseImageModel
from models.image.openai_provider import OpenAIImageModel
from models.image.dashscope_provider import DashScopeImageModel
from models import config as model_config

__all__ = [
    "BaseImageModel",
    "OpenAIImageModel",
    "DashScopeImageModel",
    "get_image_backend",
    "get_image_model",
    "generate_image",
]


_PROVIDERS: dict[str, type[BaseImageModel]] = {
    "OPENAI": OpenAIImageModel,
    "DASHSCOPE": DashScopeImageModel,
}


def _is_maas_endpoint(base_url: str) -> bool:
    """True when *base_url*'s host is maas.aliyuncs.com or a subdomain.

    Hostname parsing (instead of substring matching) keeps lookalike
    URLs such as ``https://evil.example/.maas.aliyuncs.com`` from
    selecting the DashScope backend.
    """
    candidate = base_url if "://" in base_url else f"//{base_url}"
    try:
        hostname = (urlsplit(candidate).hostname or "").casefold()
    except ValueError:
        return False
    return hostname == "maas.aliyuncs.com" or hostname.endswith(
        ".maas.aliyuncs.com",
    )


def get_image_backend() -> str:
    """Return the active image provider switch (DASHSCOPE / OPENAI).
    Priority: request-scoped Tool Config > env var > persisted model_config.json > default.

    The persisted-config fallback matters for background workers (specialist
    supervisor, continuations) that run outside any HTTP request and therefore
    have no request-scoped Tool Config bound — without it they would silently
    default to OPENAI even when the user saved a DashScope endpoint.
    """
    tool_cfg = model_config.get_request_tool_config(
        model_config.CREATOR_IMAGE_CONFIG_TOOL,
    )
    backend = tool_cfg.get("_image_backend")
    if backend:
        return backend.strip().upper()
    configured = os.environ.get("IMAGE_MODEL", "").strip().upper()
    if configured:
        return configured
    # Persisted UI config: mirror request_tool_configs()'s protocol→backend rule
    # so background workers select the same provider an in-request call would.
    user_cfg = model_config._get_user_config().get("image", {})
    if isinstance(user_cfg, dict) and user_cfg.get("enabled"):
        protocol = str(user_cfg.get("protocol") or "").casefold()
        if "dashscope" in protocol or "百炼" in protocol:
            return "DASHSCOPE"
        if "openai" in protocol:
            return "OPENAI"
        model_name = str(user_cfg.get("model_name") or "").casefold()
        base_url = str(user_cfg.get("base_url") or "").casefold()
        if (
            model_name.startswith("qwen-image")
            or "multimodal-generation" in base_url
            or "dashscope" in base_url
            or _is_maas_endpoint(base_url)
        ):
            return "DASHSCOPE"
    model_name = os.environ.get("IMAGE_MODEL_NAME", "").casefold()
    base_url = os.environ.get("IMAGE_BASE_URL", "").casefold()
    if (
        os.environ.get("DASHSCOPE_IMAGE_API_KEY")
        or model_name.startswith("qwen-image")
        or "multimodal-generation" in base_url
        or "dashscope" in base_url
        or _is_maas_endpoint(base_url)
    ):
        return "DASHSCOPE"
    return "OPENAI"


def get_image_model() -> BaseImageModel:
    """Return the image model provider selected by the current configuration."""
    provider_cls = _PROVIDERS.get(get_image_backend(), OpenAIImageModel)
    return provider_cls.from_config()


async def generate_image(
    prompt: str,
    aspect_ratio: str = "16:9",
    reference_image_urls: list[str] | None = None,
) -> str:
    """Generate an image and return a /generated/... URL."""
    model = get_image_model()
    return await model.generate(
        prompt,
        aspect_ratio=aspect_ratio,
        reference_image_urls=reference_image_urls,
    )

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
from models.image.gemini_provider import GeminiImageModel
from models.image.ark_provider import ArkImageModel
from models.image.bfl_provider import BFLImageModel
from models.image.ideogram_provider import IdeogramImageModel
from models import config as model_config
from utils.logger import setup_logger

logger = setup_logger("models.image")

__all__ = [
    "BaseImageModel",
    "OpenAIImageModel",
    "DashScopeImageModel",
    "GeminiImageModel",
    "ArkImageModel",
    "BFLImageModel",
    "IdeogramImageModel",
    "get_image_backend",
    "get_image_model",
    "generate_image",
    "poll_image_translate_task",
]


_PROVIDERS: dict[str, type[BaseImageModel]] = {
    "OPENAI": OpenAIImageModel,
    "DASHSCOPE": DashScopeImageModel,
    "GEMINI": GeminiImageModel,
    "ARK": ArkImageModel,
    "BFL": BFLImageModel,
    "IDEOGRAM": IdeogramImageModel,
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


def _detect_backend_from_names(model_name: str, base_url: str) -> str | None:
    """Model-name / host based backend detection shared by the persisted
    config and env fallbacks. Returns ``None`` when nothing matches."""

    if model_name.startswith("gemini") or "generativelanguage" in base_url:
        return "GEMINI"
    if "seedream" in model_name or "volces.com" in base_url:
        return "ARK"
    if model_name.startswith("flux") or "bfl.ai" in base_url:
        return "BFL"
    if model_name.startswith("ideogram") or "ideogram.ai" in base_url:
        return "IDEOGRAM"
    if (
        model_name.startswith("qwen-image")
        or "multimodal-generation" in base_url
        or "dashscope" in base_url
        or _is_maas_endpoint(base_url)
    ):
        return "DASHSCOPE"
    return None


def get_image_backend() -> str:
    """Return the active image provider switch (DASHSCOPE / OPENAI / GEMINI /
    ARK / BFL / IDEOGRAM).
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
        logger.info("Image backend from tool_cfg: %s", backend)
        return backend.strip().upper()
    configured = os.environ.get("IMAGE_MODEL", "").strip().upper()
    if configured:
        logger.info("Image backend from env IMAGE_MODEL: %s", configured)
        return configured
    # Persisted UI config: mirror request_tool_configs()'s protocol→backend rule
    # so background workers select the same provider an in-request call would.
    user_cfg = model_config._get_user_config().get("image", {})
    logger.info("Image backend user_cfg: %s", user_cfg)
    if isinstance(user_cfg, dict) and user_cfg.get("enabled"):
        protocol = str(user_cfg.get("protocol") or "").casefold()
        protocol_backend = _backend_for_protocol(protocol)
        if protocol_backend is not None:
            logger.info(
                "Image backend from protocol %s: %s",
                protocol,
                protocol_backend,
            )
            return protocol_backend
        model_name = str(user_cfg.get("model_name") or "").casefold()
        base_url = str(user_cfg.get("base_url") or "").casefold()
        detected = _detect_backend_from_names(model_name, base_url)
        if detected is not None:
            logger.info(
                "Image backend from model_name/base_url: %s",
                detected,
            )
            return detected
    model_name = os.environ.get("IMAGE_MODEL_NAME", "").casefold()
    base_url = os.environ.get("IMAGE_BASE_URL", "").casefold()
    if os.environ.get("DASHSCOPE_IMAGE_API_KEY"):
        logger.info("Image backend from env fallback: DASHSCOPE")
        return "DASHSCOPE"
    detected = _detect_backend_from_names(model_name, base_url)
    if detected is not None:
        logger.info("Image backend from env fallback: %s", detected)
        return detected
    logger.info("Image backend default: OPENAI")
    return "OPENAI"


def _backend_for_protocol(protocol: str) -> str | None:
    """Map a persisted protocol label onto a provider switch."""

    if "dashscope" in protocol or "百炼" in protocol:
        return "DASHSCOPE"
    if "token plan" in protocol or "tokenplan" in protocol:
        return "DASHSCOPE"
    if "gemini" in protocol:
        return "GEMINI"
    if "volcano" in protocol or "火山" in protocol or "ark" in protocol:
        return "ARK"
    if "flux" in protocol or "black forest" in protocol or "bfl" in protocol:
        return "BFL"
    if "ideogram" in protocol:
        return "IDEOGRAM"
    if "openai" in protocol:
        return "OPENAI"
    return None


def get_image_model() -> BaseImageModel:
    """Return the image model provider selected by the current configuration."""
    provider_cls = _PROVIDERS.get(get_image_backend(), OpenAIImageModel)
    return provider_cls.from_config()


async def poll_image_translate_task(task_id: str) -> dict:
    """Poll one already-submitted (billed) translation task.

    Exposed for restart recovery: the provider task id lives in the paying
    Task's durable ledger, so recovery can resume the wait instead of
    discarding a paid result.
    """

    model = get_image_model()
    poll = getattr(model, "poll_translate_task", None)
    if poll is None:
        raise NotImplementedError(
            f"{type(model).__name__} does not support translate tasks",
        )
    return await poll(task_id)


async def generate_image(
    prompt: str,
    aspect_ratio: str = "16:9",
    reference_image_urls: list[str] | None = None,
    mode: str = "generate",
    source_lang: str = "",
    target_lang: str = "",
) -> dict:
    """Generate an image and return ``{"url": local, "source_url": original}``."""
    model = get_image_model()
    return await model.generate(
        prompt,
        aspect_ratio=aspect_ratio,
        reference_image_urls=reference_image_urls,
        mode=mode,
        source_lang=source_lang,
        target_lang=target_lang,
    )

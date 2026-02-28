# -*- coding: utf-8 -*-
"""Auto-discover a vision-capable model from configured providers.

When no explicit VLM is configured, this module searches all configured
providers for a model that supports image input, mirroring OpenClaw's
``resolveAutoEntries`` pattern.

Reuses :func:`model_capabilities.supports_input_capability` for the
actual capability check to avoid duplicating hint lists and metadata
scanning.
"""

from __future__ import annotations

import logging
from typing import Optional

from .model_capabilities import supports_input_capability
from ..providers import (
    PROVIDERS,
    ResolvedModelConfig,
    load_providers_json,
)

logger = logging.getLogger(__name__)

_DEFAULT_VLM_MODELS: dict[str, str] = {
    "dashscope": "qwen-vl-max",
    "modelscope": "Qwen/Qwen2.5-VL-72B-Instruct",
}


def auto_discover_vlm(
    active_llm_cfg: ResolvedModelConfig | None,
) -> Optional[ResolvedModelConfig]:
    """Find a vision-capable model from configured providers.

    Strategy (in priority order):
    1. Check if the active LLM's provider has a known default VLM model.
    2. Scan all configured providers for models that pass
       ``supports_input_capability(..., "image")``.

    Returns ``None`` if no suitable model is found.
    """
    data = load_providers_json()

    # 1. Try the same provider as the active LLM first — use known defaults.
    if active_llm_cfg and active_llm_cfg.provider_id:
        pid = active_llm_cfg.provider_id
        default_vlm = _DEFAULT_VLM_MODELS.get(pid)
        if default_vlm:
            base_url, api_key = data.get_credentials(pid)
            defn = PROVIDERS.get(pid)
            if api_key or (defn and defn.is_local):
                logger.debug("Auto-VLM: using default VLM %s/%s", pid, default_vlm)
                return ResolvedModelConfig(
                    provider_id=pid,
                    model=default_vlm,
                    base_url=base_url,
                    api_key=api_key,
                    is_local=bool(defn and defn.is_local),
                )

    # 2. Scan built-in + extra models across all configured providers.
    for pid, defn in PROVIDERS.items():
        if not data.is_configured(defn):
            continue
        all_models = list(defn.models)
        settings = data.providers.get(pid)
        if settings:
            all_models.extend(settings.extra_models)
        for model_info in all_models:
            candidate = ResolvedModelConfig(provider_id=pid, model=model_info.id)
            if supports_input_capability(candidate, "image"):
                base_url, api_key = data.get_credentials(pid)
                logger.debug("Auto-VLM: found vision model %s/%s", pid, model_info.id)
                return ResolvedModelConfig(
                    provider_id=pid,
                    model=model_info.id,
                    base_url=base_url,
                    api_key=api_key,
                    is_local=defn.is_local,
                )

    # 3. Check custom providers.
    for pid, cpd in data.custom_providers.items():
        if not (cpd.base_url or cpd.default_base_url):
            continue
        for model_info in cpd.models:
            candidate = ResolvedModelConfig(provider_id=pid, model=model_info.id)
            if supports_input_capability(candidate, "image"):
                base_url = cpd.base_url or cpd.default_base_url
                logger.debug("Auto-VLM: found custom provider model %s/%s", pid, model_info.id)
                return ResolvedModelConfig(
                    provider_id=pid,
                    model=model_info.id,
                    base_url=base_url,
                    api_key=cpd.api_key,
                )

    logger.debug("Auto-VLM: no vision-capable model found")
    return None

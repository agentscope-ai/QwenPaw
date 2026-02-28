# -*- coding: utf-8 -*-
"""Model capability helpers used by runtime routing."""

from __future__ import annotations

import os

from ..providers import ResolvedModelConfig, get_provider, load_providers_json

# Conservative defaults: prefer explicit VLM slot unless model is clearly vision-capable.
_VISION_HINTS = (
    "gpt-4o",
    "gpt-4.1",
    "gemini",
    "qwen-vl",
    "qvq",
    "llava",
    "internvl",
    "minicpm-v",
    "glm-4v",
    "doubao-vision",
    "claude-3",
    "claude-sonnet-4",
)
_AUDIO_HINTS = (
    "gpt-4o",
    "gemini",
    "whisper",
    "voxtral",
    "audio",
)
_VIDEO_HINTS = (
    "gemini",
    "video",
    "4o",
    "4.1",
)


def _parse_csv_env(name: str) -> set[str]:
    raw = os.getenv(name, "")
    values = [v.strip().lower() for v in raw.split(",") if v.strip()]
    return set(values)


def _get_caps_from_model_metadata(
    model_cfg: ResolvedModelConfig,
) -> set[str] | None:
    model_name = model_cfg.model.strip().lower()
    if not model_cfg.provider_id:
        return None
    providers_data = load_providers_json()
    provider_id = model_cfg.provider_id
    provider_def = get_provider(provider_id)
    if provider_def is not None:
        builtin_models = list(provider_def.models)
        settings = providers_data.providers.get(provider_id)
        if settings is not None:
            builtin_models.extend(settings.extra_models)
        for item in builtin_models:
            if item.id.strip().lower() == model_name:
                return {cap.strip().lower() for cap in item.input_capabilities}

    cpd = providers_data.custom_providers.get(provider_id)
    if cpd is not None:
        for item in cpd.models:
            if item.id.strip().lower() == model_name:
                return {cap.strip().lower() for cap in item.input_capabilities}
    return None


def supports_input_capability(
    model_cfg: ResolvedModelConfig | None,
    capability: str,
) -> bool:
    """Best-effort check for whether model can accept given media capability."""
    if model_cfg is None or not model_cfg.model:
        return False

    cap = capability.strip().lower()
    if cap not in {"image", "audio", "video"}:
        return False

    model_name = model_cfg.model.strip().lower()
    if not model_name:
        return False

    deny = _parse_csv_env(f"COPAW_NON_{cap.upper()}_MODELS")
    if model_name in deny:
        return False

    allow = _parse_csv_env(f"COPAW_{cap.upper()}_MODELS")
    if model_name in allow:
        return True

    caps = _get_caps_from_model_metadata(model_cfg)
    if caps is not None:
        return cap in caps

    hints = (
        _VISION_HINTS
        if cap == "image"
        else _AUDIO_HINTS
        if cap == "audio"
        else _VIDEO_HINTS
    )
    return any(hint in model_name for hint in hints)


def supports_vision(model_cfg: ResolvedModelConfig | None) -> bool:
    """Backward compatible helper for image capability checks."""
    return supports_input_capability(model_cfg, "image")


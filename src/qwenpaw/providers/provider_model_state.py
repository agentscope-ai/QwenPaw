# -*- coding: utf-8 -*-
"""Helpers for persisted runtime state of built-in provider models."""

from typing import Any

from .context_windows import DEFAULT_CONTEXT_WINDOW
from .provider import ModelInfo

PERSISTED_MODEL_STATE_FIELDS = (
    "generate_kwargs",
    "max_tokens",
    "max_input_length",
    "max_input_length_configured",
    "max_input_length_auto_detected",
    "relay_reasoning",
    "thinking_enabled",
    "thinking_budget",
    "reasoning_effort",
    "supports_multimodal",
    "supports_image",
    "supports_video",
    "availability_status",
    "availability_message",
    "availability_http_status",
    "availability_retryable",
    "availability_checked_at",
    "availability_verification",
    "probe_source",
    "is_free",
    "config_overrides",
)


def serialize_model_state(model: ModelInfo) -> dict[str, Any]:
    """Return the mutable state which must survive a manager restart."""
    state = {
        field: getattr(model, field) for field in PERSISTED_MODEL_STATE_FIELDS
    }
    if "max_input_length_configured" not in model.model_fields_set:
        state.pop("max_input_length_configured", None)
    return state


def restore_model_state(model: ModelInfo, state: dict[str, Any]) -> None:
    """Restore mutable persisted state onto a built-in model definition."""
    generate_kwargs = state.get("generate_kwargs")
    if generate_kwargs:
        model.generate_kwargs = generate_kwargs

    for field in PERSISTED_MODEL_STATE_FIELDS:
        if field in {
            "generate_kwargs",
            "max_input_length_configured",
        }:
            continue
        value = state.get(field)
        if value is not None:
            setattr(model, field, value)

    configured_flag = state.get("max_input_length_configured")
    if configured_flag is None:
        configured_length = state.get("max_input_length")
        configured_flag = (
            configured_length is not None
            and configured_length != DEFAULT_CONTEXT_WINDOW
        )
    model.max_input_length_configured = bool(configured_flag)

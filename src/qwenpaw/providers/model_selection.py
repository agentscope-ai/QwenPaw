# -*- coding: utf-8 -*-
"""Shared parsing and precedence for per-request model selection."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from ..utils.logging import sanitize_log_value

logger = logging.getLogger(__name__)

_runtime_model: ContextVar[Any] = ContextVar("runtime_model", default=None)


@contextmanager
def runtime_model_context(model):
    """Expose the executing model to tools without changing agent defaults."""
    token = _runtime_model.set(model)
    try:
        yield
    finally:
        _runtime_model.reset(token)


def current_model_slot():
    """Resolve the executing wrapper's model, including active fallbacks."""
    key = getattr(_runtime_model.get(), "model_key", None)
    if isinstance(key, str) and ":" in key:
        return resolve_model_slot_override(key)
    return None


def request_model_override(request: Any) -> Any:
    """Prefer the direct request override to its request-context fallback."""
    if isinstance(request, dict):
        override = request.get("model_slot_override")
        context = (
            request.get("request_context")
            or (request.get("meta") or {}).get("request_context")
            or {}
        )
    else:
        override = getattr(request, "model_slot_override", None)
        context = getattr(request, "request_context", None) or {}
    if override is None:
        override = context.get("model_slot_override")
    return override


def resolve_model_slot_override(model_slot_override: Any):
    """Parse an optional model slot using the model factory's input forms."""
    from ..config.config import ModelSlotConfig

    if model_slot_override is None:
        return None
    if isinstance(model_slot_override, ModelSlotConfig):
        return model_slot_override
    if isinstance(model_slot_override, dict):
        try:
            return ModelSlotConfig.model_validate(model_slot_override)
        except (ValueError, TypeError):
            logger.warning(
                "Ignoring invalid model_slot_override dict: %s",
                sanitize_log_value(model_slot_override),
            )
    elif isinstance(model_slot_override, str):
        # Model names may themselves contain colons (e.g. version tags).
        provider_id, sep, model_name = model_slot_override.partition(":")
        if sep and provider_id.strip() and model_name.strip():
            return ModelSlotConfig(
                provider_id=provider_id.strip(),
                model=model_name.strip(),
            )
        logger.warning(
            "Ignoring invalid model_slot_override string: %s",
            sanitize_log_value(model_slot_override),
        )
    else:
        logger.warning(
            "Unsupported model_slot_override type: %s",
            sanitize_log_value(type(model_slot_override).__name__),
        )
    return None

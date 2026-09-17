# -*- coding: utf-8 -*-
"""Resolve the chat model an Agent should use for a request."""

from __future__ import annotations

from typing import Any

from ..config.config import ModelSlotConfig
from ..exceptions import ProviderError
from ..providers import ProviderManager


def resolve_effective_model(
    agent_config: Any,
    provider_manager: Any = None,
) -> ModelSlotConfig:
    """Return the validated explicit Agent model or global default.

    ``active_model`` being absent/empty means inheritance.  This resolver is
    deliberately read-only: callers remain responsible for persistence and
    runtime reloads.
    """
    manager = provider_manager or ProviderManager.get_instance()
    configured = getattr(agent_config, "active_model", None)
    slot = _normalise_slot(configured)
    if slot is None:
        slot = _normalise_slot(manager.get_active_model())
        if slot is None:
            raise ProviderError(
                message=(
                    "No active model configured. "
                    "Please configure a model using 'qwenpaw models config' "
                    "or set an agent-specific model."
                ),
            )
    provider = manager.get_provider(slot.provider_id)
    if provider is None:
        raise ProviderError(
            message=f"Provider '{slot.provider_id}' not found.",
        )
    has_model = getattr(provider, "has_model", None)
    if callable(has_model) and not has_model(slot.model):
        raise ProviderError(
            message=(
                f"Model '{slot.model}' not found for provider "
                f"'{slot.provider_id}'."
            ),
        )
    return slot


def _normalise_slot(value: Any) -> ModelSlotConfig | None:
    if value is None:
        return None
    if isinstance(value, ModelSlotConfig):
        slot = value
    elif isinstance(value, dict):
        slot = ModelSlotConfig.model_validate(value)
    else:
        slot = ModelSlotConfig.model_validate(value.model_dump())
    if not slot.provider_id or not slot.model:
        return None
    return slot

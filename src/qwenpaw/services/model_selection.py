# -*- coding: utf-8 -*-
"""Resolve request, session, agent, and global model selections."""

from __future__ import annotations

import logging
from typing import Any, Literal

from ..config.config import ModelSlotConfig

logger = logging.getLogger(__name__)

ModelSource = Literal["request", "session", "agent", "global", "none"]


def parse_model_slot(value: Any) -> ModelSlotConfig | None:
    """Normalize a supported model override representation."""
    slot: ModelSlotConfig | None = None
    if isinstance(value, ModelSlotConfig):
        slot = value
    elif isinstance(value, dict):
        try:
            slot = ModelSlotConfig.model_validate(value)
        except Exception:
            logger.warning("Ignoring invalid model slot: %r", value)
    elif isinstance(value, str):
        provider_id, separator, model = value.partition(":")
        if separator and provider_id.strip() and model.strip():
            slot = ModelSlotConfig(
                provider_id=provider_id.strip(),
                model=model.strip(),
            )
        else:
            logger.warning("Ignoring invalid model slot: %r", value)
    elif value is not None:
        provider_id = getattr(value, "provider_id", None)
        model = getattr(value, "model", None)
        if isinstance(provider_id, str) and isinstance(model, str):
            slot = ModelSlotConfig(provider_id=provider_id, model=model)
        else:
            logger.warning(
                "Ignoring unsupported model slot type: %s",
                type(value).__name__,
            )

    if slot and slot.provider_id and slot.model:
        return slot
    return None


def session_model_slot(meta: dict[str, Any] | None) -> ModelSlotConfig | None:
    """Read a persisted model override from Chat runtime metadata."""
    if not isinstance(meta, dict):
        return None
    runtime_context = meta.get("runtime_context")
    if not isinstance(runtime_context, dict):
        return None
    return parse_model_slot(runtime_context.get("model_slot_override"))


def resolve_effective_model_slot(
    *,
    request_override: Any = None,
    chat_meta: dict[str, Any] | None = None,
    agent_model: Any = None,
    global_model: Any = None,
) -> tuple[ModelSlotConfig | None, ModelSource]:
    """Resolve one model using the canonical request-to-global priority."""
    candidates: tuple[tuple[ModelSource, Any], ...] = (
        ("request", request_override),
        ("session", session_model_slot(chat_meta)),
        ("agent", agent_model),
        ("global", global_model),
    )
    for source, value in candidates:
        slot = parse_model_slot(value)
        if slot is not None:
            return slot, source
    return None, "none"


def resolve_current_model_slot(
    *,
    agent_id: str | None = None,
    request_override: Any = None,
) -> tuple[ModelSlotConfig | None, ModelSource]:
    """Resolve the model for the current runtime request."""
    from ..app.agent_context import (
        get_current_agent_id,
        get_current_model_slot_override,
    )
    from ..config.config import load_agent_config
    from ..providers.provider_manager import ProviderManager

    resolved_agent_id = agent_id
    if resolved_agent_id is None:
        resolved_agent_id = get_current_agent_id()
    if request_override is None:
        request_override = get_current_model_slot_override()

    agent_model = None
    if resolved_agent_id:
        try:
            agent_model = load_agent_config(resolved_agent_id).active_model
        except Exception:
            logger.debug(
                "Unable to load agent model for %s",
                resolved_agent_id,
                exc_info=True,
            )

    manager = ProviderManager.get_instance()
    return resolve_effective_model_slot(
        request_override=request_override,
        agent_model=agent_model,
        global_model=manager.get_active_model(),
    )

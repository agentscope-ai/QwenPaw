# -*- coding: utf-8 -*-
"""Resolve request, session, agent, and global model selections."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Literal

from ..config.config import ModelSlotConfig

logger = logging.getLogger(__name__)

ModelSource = Literal["request", "session", "agent", "global", "none"]


@dataclass(frozen=True)
class ModelSelectionContext:
    """Resolved model state shared by every consumer in one request."""

    slot: ModelSlotConfig | None
    source: ModelSource
    chat_id: str | None = None
    session_slot: ModelSlotConfig | None = None
    agent_slot: ModelSlotConfig | None = None
    global_slot: ModelSlotConfig | None = None


_current_model_context: ContextVar[ModelSelectionContext | None] = ContextVar(
    "current_model_context",
    default=None,
)


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
        raw_provider_id = getattr(value, "provider_id", None)
        raw_model = getattr(value, "model", None)
        if isinstance(raw_provider_id, str) and isinstance(raw_model, str):
            slot = ModelSlotConfig(
                provider_id=raw_provider_id,
                model=raw_model,
            )
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


def _select_model_slot(
    *,
    request_slot: ModelSlotConfig | None = None,
    session_slot: ModelSlotConfig | None = None,
    agent_slot: ModelSlotConfig | None = None,
    global_slot: ModelSlotConfig | None = None,
) -> tuple[ModelSlotConfig | None, ModelSource]:
    """Select the first normalized slot in canonical priority order."""
    candidates: tuple[
        tuple[ModelSource, ModelSlotConfig | None],
        ...,
    ] = (
        ("request", request_slot),
        ("session", session_slot),
        ("agent", agent_slot),
        ("global", global_slot),
    )
    for source, slot in candidates:
        if slot is not None:
            return slot, source
    return None, "none"


def resolve_effective_model_slot(
    *,
    request_override: Any = None,
    chat_meta: dict[str, Any] | None = None,
    session_override: Any = None,
    agent_model: Any = None,
    global_model: Any = None,
) -> tuple[ModelSlotConfig | None, ModelSource]:
    """Resolve one model using the canonical request-to-global priority."""
    normalized_session = (
        parse_model_slot(session_override)
        if session_override is not None
        else session_model_slot(chat_meta)
    )
    return _select_model_slot(
        request_slot=parse_model_slot(request_override),
        session_slot=normalized_session,
        agent_slot=parse_model_slot(agent_model),
        global_slot=parse_model_slot(global_model),
    )


async def prepare_model_context(
    *,
    workspace: Any,
    session_id: str,
    user_id: str,
    channel: str,
    request_override: Any,
) -> ModelSelectionContext:
    """Persist an input override and resolve one immutable request context."""
    clear_current_model_context()
    request_slot = parse_model_slot(request_override)
    if request_override is not None and request_slot is None:
        raise ValueError("Invalid model_slot_override")

    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        user_id,
        channel,
    )
    from ..providers.provider_manager import ProviderManager

    if request_slot is not None:
        updated = await workspace.chat_manager.set_model_slot_override(
            chat.id,
            request_slot.model_dump(),
        )
        chat = updated or chat

    session_slot = session_model_slot(chat.meta)
    agent_slot = parse_model_slot(workspace.config.active_model)
    manager = ProviderManager.get_instance()
    global_slot = parse_model_slot(
        (
            manager.get_active_model()
            if hasattr(manager, "get_active_model")
            else None
        ),
    )
    slot, source = _select_model_slot(
        request_slot=request_slot,
        session_slot=session_slot,
        agent_slot=agent_slot,
        global_slot=global_slot,
    )
    context = ModelSelectionContext(
        slot=slot,
        source=source,
        chat_id=chat.id,
        session_slot=session_slot,
        agent_slot=agent_slot,
        global_slot=global_slot,
    )
    _current_model_context.set(context)
    return context


def get_current_model_context() -> ModelSelectionContext | None:
    """Return the model context prepared for the current request."""
    return _current_model_context.get()


def set_current_model_context(context: ModelSelectionContext) -> None:
    """Replace the current request's model context after a command update."""
    _current_model_context.set(context)


def clear_current_model_context() -> None:
    """Clear request-local model state, primarily for isolated callers."""
    _current_model_context.set(None)


def get_current_model_slot(
    *,
    agent_id: str | None = None,
    request_override: Any = None,
    agent_model: Any = None,
) -> tuple[ModelSlotConfig | None, ModelSource]:
    """Return the prepared model, with a fallback outside runtime requests."""
    context = get_current_model_context()
    if context is not None:
        if request_override is None:
            return context.slot, context.source
        return _select_model_slot(
            request_slot=parse_model_slot(request_override),
            session_slot=context.session_slot,
            agent_slot=context.agent_slot,
            global_slot=context.global_slot,
        )

    if agent_model is None and agent_id:
        try:
            from ..config.config import load_agent_config

            agent_model = load_agent_config(agent_id).active_model
        except Exception:
            logger.debug(
                "Unable to load agent model for %s",
                agent_id,
                exc_info=True,
            )

    from ..providers.provider_manager import ProviderManager

    manager = ProviderManager.get_instance()
    return resolve_effective_model_slot(
        request_override=request_override,
        agent_model=agent_model,
        global_model=(
            manager.get_active_model()
            if hasattr(manager, "get_active_model")
            else None
        ),
    )


def get_current_model_info() -> tuple[Any | None, ModelSlotConfig | None]:
    """Return ModelInfo and slot for the effective model in this request."""
    try:
        from ..providers.provider_manager import ProviderManager

        slot, _source = get_current_model_slot()
        if slot is None:
            return None, None
        provider = ProviderManager.get_instance().get_provider(
            slot.provider_id,
        )
        if provider is None:
            return None, slot
        model_info = next(
            (
                item
                for item in provider.models + provider.extra_models
                if item.id == slot.model
            ),
            None,
        )
        return model_info, slot
    except Exception:
        logger.debug("Unable to resolve current model info", exc_info=True)
        return None, None


def update_current_model_context(
    slot: ModelSlotConfig | None,
    source: ModelSource,
) -> ModelSelectionContext | None:
    """Update the prepared context after ``/model`` changes Chat metadata."""
    context = get_current_model_context()
    if context is None:
        return None
    session_slot = slot if source in {"request", "session"} else None
    updated = replace(
        context,
        slot=slot,
        source=source,
        session_slot=session_slot,
    )
    set_current_model_context(updated)
    return updated

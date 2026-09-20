# -*- coding: utf-8 -*-
"""Resolve persistent session thinking without mutating agent defaults."""

from ..config.config import load_agent_config
from ..providers.provider_manager import ProviderManager
from ..providers.hub_managed import hub_mode, managed_provider, managed_slot
from ..providers.thinking import (
    ThinkingControl,
    ThinkingPreference,
    resolve_thinking,
)
from ..utils.io_utils import run_sync_io


def session_preference(meta: dict | None) -> ThinkingPreference | None:
    """Read the typed setting from the session runtime namespace."""
    raw = ((meta or {}).get(f"runtime_context") or {}).get(f"thinking")
    return ThinkingPreference.model_validate(raw) if raw is not None else None


async def thinking_view(workspace, override=None) -> dict:
    """Return requested and effective values plus model-owned constraints."""
    config = await run_sync_io(load_agent_config, workspace.agent_id)
    inherited = ThinkingPreference(
        level=config.thinking_level,
        budget_tokens=config.thinking_budget,
    )
    requested = (
        override if override and override.level != f"inherit" else inherited
    )

    def model_view():
        if config.backend != f"qwenpaw":
            return None, ThinkingControl()
        if hub_mode():
            slot, catalog = managed_slot(config.active_model)
            if slot is None:
                return None, ThinkingControl()
            provider = managed_provider(catalog)
            return slot.model, provider.thinking_control(slot.model)
        manager = ProviderManager.get_instance()
        slot = config.active_model or manager.get_active_model()
        if not slot:
            return None, ThinkingControl()
        provider = manager.get_provider(slot.provider_id)
        if provider is None:
            return None, ThinkingControl()
        control = provider.thinking_control(slot.model)
        return slot.model, control

    model, control = await run_sync_io(model_view)
    effective, reason = resolve_thinking(requested, control)
    return {
        f"model": model,
        f"control": control.model_dump(),
        f"value": (override or ThinkingPreference()).model_dump(),
        f"effective": effective.model_dump(),
        f"source": (
            f"session"
            if override and override.level != f"inherit"
            else f"agent"
            if inherited.level != f"inherit"
            else f"model"
        ),
        f"reason": reason,
    }


async def apply_session_thinking(ctx, config):
    """Snapshot one session's preference before creating its runtime."""
    workspace = getattr(ctx, f"workspace", None)
    manager = getattr(workspace, f"chat_manager", None)
    session_id = getattr(ctx, f"session_id", None)
    if not manager or not session_id:
        return config
    request = getattr(ctx, f"request", None)
    request_context = getattr(request, f"request_context", None) or {}
    if request_context.get(f"_spawn_subagent"):
        session_id = request_context.get(f"parent_session_id") or session_id
    chat_id = await manager.get_chat_id_by_session(
        session_id,
        getattr(request, f"channel", None) or f"console",
        getattr(request, f"user_id", None) or None,
    )
    chat = await manager.get_chat(chat_id) if chat_id else None
    preference = session_preference(chat.meta) if chat else None
    if preference is None or preference.level == f"inherit":
        return config
    return config.model_copy(
        update={
            f"thinking_level": preference.level,
            f"thinking_budget": preference.budget_tokens,
        },
        deep=True,
    )

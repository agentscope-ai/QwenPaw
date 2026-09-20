# -*- coding: utf-8 -*-
"""Resolve persistent session thinking without mutating agent defaults."""

from ..config.config import ModelSlotConfig, load_agent_config
from ..providers.provider_manager import ProviderManager
from ..providers.hub_managed import hub_mode, managed_provider, managed_slot
from ..providers.thinking import (
    ThinkingControl,
    ThinkingPreference,
    resolve_thinking,
)
from ..utils.io_utils import run_sync_io


def session_model(meta: dict | None) -> ModelSlotConfig | None:
    """Read the selected model owned by this conversation."""
    raw = ((meta or {}).get(f"runtime_context") or {}).get(f"model")
    return ModelSlotConfig.model_validate(raw) if raw is not None else None


def session_preference(
    meta: dict | None,
    model_key: str = f"",
) -> ThinkingPreference | None:
    """Read reasoning settings for one provider/model in this session."""
    settings = ((meta or {}).get(f"runtime_context") or {}).get(
        f"thinking",
        {},
    )
    raw = settings.get(model_key)
    return ThinkingPreference.model_validate(raw) if raw is not None else None


def _with_session_model(config, selected):
    """Keep agent reasoning defaults attached to the agent's own model."""
    if selected is None:
        return config
    default = config.active_model
    if default is None:
        if hub_mode():
            default, _ = managed_slot(None)
        else:
            default = ProviderManager.get_instance().get_active_model()
    update = {f"active_model": selected}
    if default != selected:
        update.update(thinking_level=f"inherit", thinking_budget=None)
    return config.model_copy(update=update)


async def thinking_view(
    workspace,
    override=None,
    model_override=None,
    *,
    meta=None,
) -> dict:
    """Return requested and effective values plus model-owned constraints."""
    config = await run_sync_io(load_agent_config, workspace.agent_id)
    config = await run_sync_io(_with_session_model, config, model_override)
    inherited = ThinkingPreference(
        level=config.thinking_level,
        budget_tokens=config.thinking_budget,
    )

    def model_view():
        if config.backend != f"qwenpaw":
            return None, None, ThinkingControl(), None
        if hub_mode():
            slot, catalog = managed_slot(config.active_model)
            if slot is None:
                return None, None, ThinkingControl(), None
            provider = managed_provider(catalog)
            return (
                slot.provider_id,
                slot.model,
                provider.thinking_control(slot.model),
                provider.get_context_size(slot.model),
            )
        manager = ProviderManager.get_instance()
        slot = config.active_model or manager.get_active_model()
        if not slot:
            return None, None, ThinkingControl(), None
        provider = manager.get_provider(slot.provider_id)
        if provider is None:
            return None, None, ThinkingControl(), None
        control = provider.thinking_control(slot.model)
        return (
            slot.provider_id,
            slot.model,
            control,
            provider.get_context_size(slot.model),
        )

    provider_id, model, control, context_size = await run_sync_io(model_view)
    model_key = f"{provider_id}:{model}" if model else f""
    if override is None and meta is not None:
        override = session_preference(meta, model_key)
    requested = (
        override if override and override.level != f"inherit" else inherited
    )
    effective, reason = resolve_thinking(requested, control)
    return {
        f"model": model,
        f"provider_id": provider_id,
        f"model_key": model_key,
        f"effective_max_input_length": context_size,
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
    selected = session_model(chat.meta) if chat else None
    config = await run_sync_io(_with_session_model, config, selected)
    if chat:

        def selected_key():
            if hub_mode():
                slot, _ = managed_slot(config.active_model)
            else:
                slot = config.active_model or (
                    ProviderManager.get_instance().get_active_model()
                )
            return f"{slot.provider_id}:{slot.model}" if slot else f""

        model_key = await run_sync_io(selected_key)
        preference = session_preference(chat.meta, model_key)
    else:
        preference = None
    if preference is None or preference.level == f"inherit":
        return config
    return config.model_copy(
        update={
            f"thinking_level": preference.level,
            f"thinking_budget": preference.budget_tokens,
        },
        deep=True,
    )

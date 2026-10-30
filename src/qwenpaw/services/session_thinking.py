# -*- coding: utf-8 -*-
"""Resolve conversation model and thinking without mutating agent defaults."""

from ..config.config import ModelSlotConfig, load_agent_config
from ..providers.provider_manager import ProviderManager
from ..providers.provider import Provider
from ..providers.model_selection import (
    request_model_override,
    resolve_model_slot_override,
)
from ..providers.dashscope_provider import DashScopeProvider
from ..providers.gemini_provider import resolve_thinking_config
from ..providers.openai_response_provider import (
    _supports_none_reasoning_effort,
)
from ..providers.adapters.anthropic import (
    resolve_parameters,
    resolve_request_parameters,
)
from ..providers.hub_managed import (
    PROVIDER_ID,
    hub_mode,
    managed_provider,
    managed_slot,
)
from ..providers.thinking import (
    ThinkingControl,
    ThinkingPreference,
    resolve_thinking,
    model_default_thinking,
)
from ..utils.io_utils import run_sync_io


def _validate_thinking_parameters(params: dict) -> None:
    """Reject malformed display inputs without coercing user settings."""
    for key in (
        f"extra_body",
        f"chat_template_kwargs",
        f"thinking",
        f"reasoning",
        f"thinking_config",
        f"output_config",
    ):
        value = params.get(key)
        if value is not None:
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be an object")
            _validate_thinking_parameters(value)
    for keys, expected in (
        ((f"thinking_budget", f"budget_tokens"), int),
        ((f"reasoning_effort", f"effort", f"thinking_level"), str),
        (
            (
                f"enable_thinking",
                f"thinking_enable",
                f"enabled",
                f"disable_thinking",
            ),
            bool,
        ),
    ):
        for key in keys:
            value = params.get(key)
            if value is not None and type(value) is not expected:
                raise ValueError(f"Invalid type for {key}")


def _model_thinking_parameters(provider, model, info):
    """Read configured values using the serving adapter's precedence."""
    configured = next(
        (item for item in Provider.all_models(provider) if item.id == model),
        info,
    )
    params = provider._deep_merge(  # pylint: disable=protected-access
        provider.generate_kwargs,
        configured.generate_kwargs,
    )
    _validate_thinking_parameters(params)
    if isinstance(provider, DashScopeProvider):
        params = provider.resolve_thinking_kwargs(model, params)
    elif provider.thinking_wire_protocol == f"gemini":
        params = resolve_thinking_config(params)
    elif params.get(f"disable_thinking"):
        if provider.model_protocol(model) == f"responses":
            if not _supports_none_reasoning_effort(model):
                return {}
        return {f"enable_thinking": False}
    return params


def _model_default_thinking(provider: Provider, model: str):
    """Keep invalid generation settings from breaking the display endpoint."""
    try:
        return _resolve_model_default_thinking(provider, model)
    except (TypeError, ValueError):
        return ThinkingPreference()


def _resolve_model_default_thinking(provider: Provider, model: str):
    """Read declared defaults without changing inherited request settings."""
    info = provider.resolve_model_info(model)
    control = provider.thinking_control(model)
    params = _model_thinking_parameters(provider, model, info)
    native_anthropic = provider.model_protocol(model) == f"anthropic"
    if native_anthropic:
        parameters, extra = resolve_parameters(params, info.max_output_length)
        params = resolve_request_parameters(parameters, extra)
        thinking = (params.get(f"extra_body") or {}).get(
            f"thinking",
            params.get(f"thinking"),
        )
        if thinking is None:
            return ThinkingPreference(level=f"off")
    return model_default_thinking(
        params,
        control,
        default_enabled=info.thinking_enabled,
        default_effort=info.reasoning_effort,
        default_budget=info.thinking_budget,
        native_anthropic=native_anthropic,
    )


def session_model(meta: dict | None) -> ModelSlotConfig | None:
    """Read the selected model owned by this conversation."""
    raw = ((meta or {}).get(f"runtime_context") or {}).get(f"model")
    return ModelSlotConfig.model_validate(raw) if raw is not None else None


def select_chat_model(meta=None, *, model_override=None):
    """Select a conversation override and its source using one precedence."""
    selected = resolve_model_slot_override(model_override)
    if selected is not None and selected.provider_id and selected.model:
        return selected, "request"
    selected = session_model(meta)
    return selected, "session" if selected is not None else None


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
        default = ProviderManager.get_instance().active_model
    update = {f"active_model": selected}
    if default != selected:
        update.update(thinking_level=f"inherit", thinking_budget=None)
    return config.model_copy(update=update)


def decision_settings(config, override: bool | None) -> dict:
    """Resolve the session toggle against agent and global configuration."""
    configured = config.backend == "qwenpaw" and bool(
        config.decision_model
        or ProviderManager.get_instance().default_models["decision"],
    )
    return {
        "configured": configured,
        "override": override,
        "enabled": configured
        and (
            override
            if override is not None
            else config.decision_model is not None
        ),
    }


async def thinking_view(
    workspace,
    override=None,
    model_override=None,
    *,
    meta=None,
) -> dict:
    """Return requested and effective values plus model-owned constraints."""
    config = await run_sync_io(load_agent_config, workspace.agent_id)
    model_source = (
        f"session"
        if model_override
        else f"agent"
        if config.active_model
        else f"global"
    )
    config = await run_sync_io(_with_session_model, config, model_override)
    inherited = ThinkingPreference(
        level=config.thinking_level,
        budget_tokens=config.thinking_budget,
    )

    def model_view():
        if config.backend != f"qwenpaw":
            return None, None, ThinkingControl(), None, None, None
        manager = ProviderManager.get_instance()
        slot = config.active_model or manager.get_active_model()
        if hub_mode() and slot and slot.provider_id == PROVIDER_ID:
            slot, catalog = managed_slot(slot, explicit=True)
            if slot is None:
                return None, None, ThinkingControl(), None, None, None
            provider = managed_provider(catalog)
        else:
            if not slot:
                return None, None, ThinkingControl(), None, None, None
            provider = manager.get_provider(slot.provider_id)
            if provider is None or not provider.enabled:
                return None, None, ThinkingControl(), None, None, None
        info = provider.get_model_info(slot.model)
        if info is None or getattr(info, "model_type", "chat") == "decision":
            return None, None, ThinkingControl(), None, None, None
        name = info.name
        return (
            slot.provider_id,
            slot.model,
            provider.thinking_control(slot.model),
            provider.get_context_size(slot.model),
            name,
            (
                _model_default_thinking(provider, slot.model)
                if inherited.level == f"inherit"
                else None
            ),
        )

    (
        provider_id,
        model,
        control,
        context_size,
        model_name,
        model_default,
    ) = await run_sync_io(model_view)
    model_key = f"{provider_id}:{model}" if model else f""
    if override is None and meta is not None:
        override = session_preference(meta, model_key)
    requested = (
        override if override and override.level != f"inherit" else inherited
    )
    effective, reason = resolve_thinking(requested, control)
    if effective.level == f"inherit" and model_default is not None:
        effective = model_default
    return {
        "decision": await run_sync_io(
            decision_settings,
            config,
            ((meta or {}).get("runtime_context") or {}).get(
                "decision_enabled",
            ),
        ),
        f"model_source": model_source,
        f"model": model,
        f"model_name": model_name,
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


async def get_session_chat(ctx, *, chat=None):
    """Find settings for runtime/control contexts or an already loaded chat.

    Spawned subagents use the parent conversation even when the current
    chat is supplied, as it is for background title generation.
    """
    workspace = getattr(ctx, f"workspace", None)
    manager = getattr(workspace, f"chat_manager", None)
    request = getattr(ctx, "request", None)
    if request is None:
        request = getattr(ctx, "payload", None)
    values = (
        request
        if isinstance(request, dict)
        else {
            name: getattr(request, name, None)
            for name in ("request_context", "channel", "user_id")
        }
    )
    # Console title tasks receive the native payload, before it is converted
    # into the AgentRequest used by execution.
    request_context = (
        values.get("request_context")
        or (values.get("meta") or {}).get("request_context")
        or {}
    )
    spawned = request_context.get(f"_spawn_subagent")
    if chat is not None and not spawned:
        return chat
    session_id = getattr(ctx, f"session_id", None) or getattr(
        chat,
        "session_id",
        None,
    )
    if not manager or not session_id:
        return None
    channel = (
        values.get("channel")
        or values.get("channel_id")
        or getattr(chat, "channel", None)
        or "console"
    )
    user_id = (
        values.get("user_id")
        or values.get("sender_id")
        or getattr(ctx, "user_id", None)
        or getattr(chat, "user_id", None)
        or None
    )
    if spawned:
        session_id = request_context.get(f"parent_session_id") or session_id
        # Console submissions keep the child's transport identity separate
        # from the parent conversation's owner and channel.
        channel = request_context.get("channel") or channel
        user_id = request_context.get("user_id") or user_id
    chat_id = await manager.get_chat_id_by_session(
        session_id,
        channel,
        user_id,
    )
    return await manager.get_chat(chat_id) if chat_id else None


async def apply_chat_model_settings(config, meta=None, *, model_override=None):
    """Resolve thinking for the final model: request > session > defaults."""
    selected, _source = select_chat_model(meta, model_override=model_override)
    config = await run_sync_io(_with_session_model, config, selected)
    if meta:

        def selected_key():
            slot = config.active_model or (
                ProviderManager.get_instance().get_active_model()
            )
            return f"{slot.provider_id}:{slot.model}" if slot else f""

        model_key = await run_sync_io(selected_key)
        preference = session_preference(meta, model_key)
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


async def apply_session_thinking(ctx, config):
    """Snapshot model and model-owned thinking for the calling request."""
    chat = await get_session_chat(ctx)
    request = getattr(ctx, "request", None)
    if request is None:
        request = getattr(ctx, "payload", None)
    return await apply_chat_model_settings(
        config,
        chat.meta if chat else None,
        model_override=request_model_override(request),
    )

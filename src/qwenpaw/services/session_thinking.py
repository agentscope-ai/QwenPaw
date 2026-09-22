# -*- coding: utf-8 -*-
"""Resolve persistent session thinking without mutating agent defaults."""

from ..config.config import ModelSlotConfig, load_agent_config
from ..providers.provider_manager import ProviderManager
from ..providers.provider import Provider
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
)
from ..utils.io_utils import run_sync_io


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
    else:
        thinking = None
    params = {**params, **(params.get(f"extra_body") or {})}
    thinking = thinking or params.get(f"thinking") or {}
    reasoning = params.get(f"reasoning") or {}
    config = params.get(f"thinking_config") or {}
    enabled = params.get(
        f"enable_thinking",
        params.get(f"thinking_enable"),
    )
    effort = params.get(
        f"reasoning_effort",
        reasoning.get(
            f"effort",
            (params.get(f"output_config") or {}).get(
                f"effort",
                config.get(f"thinking_level"),
            ),
        ),
    )
    budget = params.get(
        f"thinking_budget",
        thinking.get(
            f"budget_tokens",
            config.get(f"thinking_budget"),
        ),
    )
    if budget is None and effort is None and not native_anthropic:
        if enabled is None:
            enabled = info.thinking_enabled
        effort = info.reasoning_effort
    if (
        enabled is False
        or thinking.get(f"type") == f"disabled"
        or reasoning.get(f"enabled") is False
        or effort in {f"none", f"off"}
        or budget == 0
    ):
        return ThinkingPreference(level=f"off")
    if budget is None and effort in {
        f"minimal",
        f"low",
        f"medium",
        f"high",
        f"xhigh",
        f"max",
    }:
        if control.kind == f"effort" and effort in control.efforts:
            return ThinkingPreference(level=effort)
        return ThinkingPreference()
    if control.kind == f"budget":
        if budget is None and not native_anthropic:
            budget = control.budget_default
        if (
            budget is not None
            and control.budget_min is not None
            and control.budget_max is not None
            and control.budget_min <= budget <= control.budget_max
        ):
            return ThinkingPreference(level=f"budget", budget_tokens=budget)
    return ThinkingPreference()


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
        default = ProviderManager.get_instance().active_model
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
        if info is None:
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

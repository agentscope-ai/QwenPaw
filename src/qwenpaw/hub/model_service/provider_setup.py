# -*- coding: utf-8 -*-
"""Reuse provider presets and discovery with isolated Hub credentials."""

from datetime import datetime, timezone

from ...utils.io_utils import run_sync_io
from ...providers.openai_provider import OpenAIProvider
from ...providers.openrouter_provider import OpenRouterProvider
from ...providers.anthropic_provider import AnthropicProvider
from ...providers.openai_response_provider import OpenAIResponseProvider
from ...providers.provider_catalog import BUILTIN_PROVIDERS
from ...providers.provider_discovery import merge_discovered_model
from ...providers.provider import ModelInfo


def supported_presets():
    """Select built-in providers supported by the shared wire adapters."""
    return {
        provider.id: provider
        for provider in BUILTIN_PROVIDERS
        if isinstance(
            provider,
            (
                OpenAIProvider,
                OpenRouterProvider,
                AnthropicProvider,
            ),
        )
        and not provider.is_local
    }


def connection_provider(connection: dict):
    """Reuse built-in service classes; only custom connections pick a wire."""
    provider_id = connection.get(f"provider_id")
    if provider_id:
        provider = supported_presets()[provider_id].model_copy(deep=True)
    else:
        provider_class = {
            f"chat": OpenAIProvider,
            f"responses": OpenAIResponseProvider,
            f"anthropic": AnthropicProvider,
        }[connection.get(f"protocol", f"chat")]
        provider = provider_class(
            id=connection[f"id"],
            name=connection[f"name"],
        )
    provider.base_url = connection[f"base_url"]
    return provider


def provider_presets() -> list[dict]:
    """Expose only packaged provider metadata, never configured credentials."""
    return [
        {
            "id": provider.id,
            "name": provider.name,
            "base_url": provider.base_url,
            "api_key_prefix": provider.api_key_prefix,
            "api_key_prefixes": provider.api_key_prefixes,
            "freeze_url": provider.freeze_url,
            "base_url_options": provider.meta.get("base_url_options", []),
            "models": [model.model_dump() for model in provider.models],
            f"protocol": provider.wire_protocol,
        }
        for provider in supported_presets().values()
    ]


def provider_headers(connection: dict) -> dict:
    """Use the same packaged attribution headers as personal providers."""
    preset = supported_presets().get(connection.get("provider_id"))
    return preset.request_headers() if preset is not None else {}


def model_provider(model: dict, connection: dict):
    """Resolve model rules without credentials or personal data."""
    provider = connection_provider(connection)
    model_id = model["upstream_model"]
    provider.base_url = connection[f"base_url"]
    if provider.get_model_info(model_id) is None:
        provider.models.append(ModelInfo(id=model_id, name=model_id))
    card = provider.get_model_info(model_id)
    card.template_id = model.get(f"template_id")
    for field in (
        f"supports_image",
        f"supports_video",
        f"supports_audio",
        f"supports_tool_calling",
    ):
        if model.get(field) is not None:
            setattr(card, field, model[field])
            card.config_overrides.append(field)
    return provider


def published_capabilities(model: dict, connection: dict) -> dict:
    """Publish effective capabilities without upstream connection identity."""
    provider = model_provider(model, connection)
    card = provider.resolve_model_info(model[f"upstream_model"])
    native_bridge = (
        provider.model_protocol(model[f"upstream_model"]) != f"chat"
    )
    return {
        f"supports_image": card.supports_image,
        f"supports_audio": False if native_bridge else card.supports_audio,
        f"supports_video": False if native_bridge else card.supports_video,
        f"supports_tool_calling": card.supports_tool_calling,
        f"thinking_control": (
            provider.thinking_control(model[f"upstream_model"]).model_dump()
        ),
        f"supports_agent_thinking": (
            provider.supports_agent_thinking(model[f"upstream_model"])
        ),
        f"input_token_limit": (
            min(
                model[f"input_token_limit"],
                card.effective_max_input_length,
            )
            if card.context_length_source != f"default"
            else model[f"input_token_limit"]
        ),
        f"output_token_limit": (
            min(
                model[f"output_token_limit"],
                card.max_output_length,
            )
            if card.max_output_length
            else model[f"output_token_limit"]
        ),
    }


def _discovery_provider(catalog, connection_id: str):
    """Load a connection and its credential on the same worker thread."""
    connection = next(
        (
            row
            for row in catalog.rows("hub_model_connections")
            if row["id"] == connection_id
        ),
        None,
    )
    if connection is None:
        raise KeyError(connection_id)
    provider = connection_provider(connection)
    provider.base_url = connection["base_url"]
    provider.api_key = catalog.key(connection)
    provider.is_custom = True
    return provider


def preview_model(catalog, connection_id, model_id, template_id=None):
    """Resolve a custom model name without a billable probe."""
    provider = _discovery_provider(catalog, connection_id)
    return provider.model_capabilities(
        ModelInfo(
            id=model_id,
            name=model_id,
            template_id=template_id,
        ),
    )


async def discover_models(catalog, connection_id: str):
    """Merge discovery with the shared catalog without personal writes."""
    provider = await run_sync_io(_discovery_provider, catalog, connection_id)
    fetched = await provider.fetch_models(timeout=10)
    models = {model.id: model for model in provider.models}
    discovered_at = datetime.now(timezone.utc).isoformat()
    for remote in fetched:
        model = merge_discovered_model(provider, remote, discovered_at)
        model.discovery_origin = "both" if remote.id in models else "api"
        models[model.id] = model
    return [provider.model_capabilities(model) for model in models.values()]

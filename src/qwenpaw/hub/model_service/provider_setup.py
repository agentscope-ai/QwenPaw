# -*- coding: utf-8 -*-
"""Reuse provider presets and discovery with isolated Hub credentials."""

from ...providers.openai_provider import OpenAIProvider
from ...providers.openrouter_provider import OpenRouterProvider
from ...providers.provider_catalog import BUILTIN_PROVIDERS


def supported_presets():
    """Select providers compatible with the Hub Chat Completions gateway."""
    return {
        provider.id: provider
        for provider in BUILTIN_PROVIDERS
        if isinstance(provider, (OpenAIProvider, OpenRouterProvider))
        and provider.chat_model in {"OpenAIChatModel", "DashScopeChatModel"}
        and not provider.is_local
        and provider.require_api_key
    }


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
        }
        for provider in supported_presets().values()
    ]


def provider_headers(connection: dict) -> dict:
    """Use the same packaged attribution headers as personal providers."""
    preset = supported_presets().get(connection.get("provider_id"))
    return preset.request_headers() if preset is not None else {}


async def discover_models(catalog, connection_id: str):
    """Discover through an ephemeral provider with Hub-owned credentials."""
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
    preset = supported_presets().get(connection.get("provider_id"))
    provider = (
        preset.model_copy(deep=True)
        if preset is not None
        else OpenAIProvider(id=connection_id, name=connection["name"])
    )
    provider.base_url = connection["base_url"]
    provider.api_key = catalog.key(connection)
    provider.is_custom = True
    return await provider.fetch_models(timeout=10)

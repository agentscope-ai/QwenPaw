# -*- coding: utf-8 -*-
"""Provider management — models, registry + persistent store."""

from .models import (
    CustomProviderData,
    ModelSlotConfig,
    ProviderDefinition,
    ProviderSettings,
)
from .provider import Provider, ProviderInfo, ModelInfo
from .provider_manager import ProviderManager, ActiveModelsInfo

__all__ = [
    "ActiveModelsInfo",
    "CustomProviderData",
    "ModelInfo",
    "ProviderDefinition",
    "ProviderInfo",
    "ProviderSettings",
    "Provider",
    "ProviderManager",
    "ModelInfo",
    "ProviderInfo",
    "load_providers_json",
    "get_provider_chat_model",
]


def load_providers_json() -> ActiveModelsInfo:
    """Load active models configuration.

    Returns:
        ActiveModelsInfo containing the active LLM configuration.
    """
    manager = ProviderManager()
    active_llm = manager.load_active_model()
    return ActiveModelsInfo(active_llm=active_llm)


def get_provider_chat_model(
    provider_id: str,
    data: ActiveModelsInfo,  # pylint: disable=unused-argument
) -> str:
    """Get the chat model class name for a provider.

    Args:
        provider_id: The provider identifier.
        data: The active models info.

    Returns:
        The chat model class name (e.g., 'AnthropicChatModel').
    """
    if not provider_id:
        return ""

    manager = ProviderManager()
    provider = manager.get_provider(provider_id)

    if provider is None:
        return ""

    # Return the chat_model from the provider
    return provider.chat_model

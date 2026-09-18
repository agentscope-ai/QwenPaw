# -*- coding: utf-8 -*-
"""AgentScope Platform registration and configuration persistence."""

from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import ProviderManager


async def test_platform_provider_configuration_survives_reload() -> None:
    manager = ProviderManager()
    provider = manager.get_provider("agentscope-platform")
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "AgentSocpe-Platform"
    assert provider.base_url == (
        "https://platform.agentscope.io/compatible-mode/v1"
    )
    assert provider.require_api_key
    assert not provider.is_custom
    assert provider.discovery_strategy == "openai_models"

    await manager.update_provider_async(
        provider.id,
        {"api_key": "platform-test-key"},
    )
    reloaded = ProviderManager().get_provider(provider.id)
    assert reloaded is not None
    assert reloaded.api_key == "platform-test-key"
    assert reloaded.base_url == provider.base_url
    assert reloaded.meta["api_key_url"] == (
        "https://platform.agentscope.io/model-calls"
    )

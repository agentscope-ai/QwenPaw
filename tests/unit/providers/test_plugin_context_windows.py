# -*- coding: utf-8 -*-
"""Plugin display windows must use the same policy as runtime models."""
# pylint: disable=protected-access

import threading

import pytest

from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo, ProviderInfo
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.providers.plugin_provider_registry import PluginProviderRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("custom_window", [None, 777777])
async def test_plugin_windows_use_runtime_policy_off_event_loop(custom_window):
    threads = []

    class Plugin(OpenAIProvider):
        def get_context_size(self, model_id):
            threads.append(threading.get_ident())
            return custom_window or super().get_context_size(model_id)

    manager = object.__new__(ProviderManager)
    manager.builtin_providers = {}
    manager.custom_providers = {}
    info = ProviderInfo(
        id="plugin",
        name="Plugin",
        models=[
            ModelInfo(id="gpt-4.1", name="GPT-4.1"),
            ModelInfo(id="removed", name="Removed"),
        ],
        removed_model_ids=["removed"],
    )
    manager.plugin_providers = {"plugin": {"class": Plugin, "info": info}}
    manager._plugin_registry = PluginProviderRegistry(manager)
    result = (await manager.list_provider_info())[0]
    assert threads and all(value != threading.get_ident() for value in threads)
    expected = manager.get_provider("plugin").get_context_size("gpt-4.1")
    assert result.effective_context_windows == {"gpt-4.1": expected}
    assert expected > 131072
    assert info.effective_context_windows == {}
    assert result is not info

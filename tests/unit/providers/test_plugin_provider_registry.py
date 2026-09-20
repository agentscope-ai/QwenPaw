# -*- coding: utf-8 -*-
"""A malformed plugin projection hook must not break provider listing."""

from types import SimpleNamespace

from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.plugin_provider_registry import PluginProviderRegistry
from qwenpaw.providers.provider import ModelInfo, ProviderInfo


class _InstanceCatalogHook(OpenAIProvider):
    def context_catalog_enabled(self):
        return False


def test_instance_catalog_hook_leaves_only_its_registration_unprojected(
    caplog,
):
    registrations = {}
    for name, provider_class in (
        ("bad", _InstanceCatalogHook),
        ("good", OpenAIProvider),
    ):
        registrations[name] = {
            "class": provider_class,
            "info": ProviderInfo(
                id=name,
                name=name,
                models=[ModelInfo(id="gpt-4.1", name="GPT")],
            ),
        }
    manager = SimpleNamespace(plugin_providers=registrations)

    infos = PluginProviderRegistry(manager).list_provider_infos()

    assert [info.id for info in infos] == ["bad", "good"]
    assert infos[0].models[0].effective_max_input_length is None
    assert infos[1].models[0].effective_max_input_length == 1_047_576
    assert _InstanceCatalogHook.__qualname__ in caplog.text
    assert "classmethod" in caplog.text

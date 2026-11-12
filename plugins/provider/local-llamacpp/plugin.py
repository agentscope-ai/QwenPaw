# -*- coding: utf-8 -*-
"""Manage local resources through Plugin v2. Inference stays in the host."""

from qwenpaw.plugins import PluginContext
from qwenpaw.plugins.providers import ProviderSpec

from .provider import LocalProvider
from .app import create_app


# TODO: Align plugin.json's minimum SDK version with the finalized release for
# native providers, scoped storage paths and connection close budgets.
class Plugin:
    def register(self, ctx: PluginContext):
        provider = LocalProvider(ctx)
        provider.handle = ctx.register_provider(
            ProviderSpec(
                id="qwenpaw-local",
                label="Local llama.cpp",
                protocol="openai-chat",
                connect=provider.connect,
                require_api_key=False,
                is_local=True,
            ),
        )
        ctx.on_activate(provider.activate)
        ctx.register_app(create_app(provider))


plugin = Plugin()

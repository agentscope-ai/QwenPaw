# -*- coding: utf-8 -*-
"""ModelScope Skill marketplace plugin."""

from qwenpaw.market.builtin import BuiltinMarketProvider
from qwenpaw.market.providers.modelscope import ModelScopeProvider


class HubPlugin:
    def register(self, api):
        api.register_market_provider(
            BuiltinMarketProvider(ModelScopeProvider()),
            priority=20,
        )


plugin = HubPlugin()

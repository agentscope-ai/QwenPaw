# -*- coding: utf-8 -*-
"""Create host-owned AgentScope models from QwenPaw's decision slot."""

from ..exceptions import ProviderError
from ..providers import ProviderManager
from ..providers.typesafe_provider import TypeSafeProvider
from ..utils.io_utils import run_sync_io


def _decision_model_settings(agent_config):
    """Resolve the agent or global decision slot, independently of chat."""
    manager = ProviderManager.get_instance()
    slot = agent_config.decision_model or manager.default_models["decision"]
    if slot is None:
        raise ProviderError(
            message="Configure a decision model for JEV compaction",
        )
    provider = manager.get_provider(slot.provider_id)
    if not isinstance(provider, TypeSafeProvider) or not provider.enabled:
        raise ProviderError(
            message="The TypeSafe decision provider is unavailable",
        )
    provider.validate_model_selection(slot.model, "decision")
    return provider, slot.model


async def create_decision_model_async(agent_config):
    """Create an AS JEV instance using the provider credentials."""
    provider, model = await run_sync_io(_decision_model_settings, agent_config)
    return provider.as_decision_model(model)

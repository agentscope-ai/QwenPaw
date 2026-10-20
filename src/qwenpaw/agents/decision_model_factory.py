# -*- coding: utf-8 -*-
"""Create host-owned decision models from QwenPaw's existing model slots."""

from ..exceptions import ProviderError
from ..providers import ProviderManager
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
    if provider is None or not provider.enabled or not provider.api_key:
        raise ProviderError(
            message="The decision provider is unavailable or has no API key",
        )
    provider.validate_model_selection(slot.model, "decision")
    return {
        "api_key": provider.api_key,
        "base_url": provider.base_url or None,
        "model": slot.model,
    }


def _create_model(settings):
    """Construct on the consumer's thread, after cancellable settings I/O."""
    from agentscope.classifier import JevClassifierModel
    from agentscope.credential import TypeSafeCredential

    return JevClassifierModel(
        credential=TypeSafeCredential(
            api_key=settings["api_key"],
            base_url=settings["base_url"],
        ),
        model=settings["model"],
        timeout=10,
        max_retries=1,
    )


def create_decision_model(agent_config):
    """Create a host-owned client only when a consumer requests it."""
    return _create_model(_decision_model_settings(agent_config))


async def create_decision_model_async(agent_config):
    """Resolve persisted provider settings away from the event loop."""
    settings = await run_sync_io(_decision_model_settings, agent_config)
    # No await between constructing the client and returning it to its owner.
    return _create_model(settings)

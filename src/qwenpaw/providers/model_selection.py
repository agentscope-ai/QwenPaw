# -*- coding: utf-8 -*-
"""Effective model selection shared by request validation and runtime build."""

from typing import Any

from ..exceptions import ConfigurationException
from . import provider_manager


def require_effective_model(agent_config: Any) -> Any:
    """Return the effective model or raise a stable configuration error."""
    active = agent_config.active_model
    if not (active and active.provider_id and active.model):
        active = (
            provider_manager.ProviderManager.get_instance().get_active_model()
        )
    if active is None or not active.provider_id or not active.model:
        raise ConfigurationException(
            "No active model configured; pick one in the UI",
            config_key="active_model",
            error_code="MODEL_NOT_CONFIGURED",
        )
    return active

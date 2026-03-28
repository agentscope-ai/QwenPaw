# -*- coding: utf-8 -*-
"""App-level exception types."""

from agentscope_runtime.engine.schemas.exception import (
    ConfigurationException,
)


class AgentReloadRequiresRestartError(ConfigurationException):
    """Raised when an agent contains clients unsafe for hot reload."""

    def __init__(self, message: str):
        super().__init__("agent_reload.hot_reload_safe", message)

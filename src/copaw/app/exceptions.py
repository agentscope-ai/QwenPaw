# -*- coding: utf-8 -*-
"""App-level exception types."""


class AgentReloadRequiresRestartError(RuntimeError):
    """Raised when an agent contains clients unsafe for hot reload."""

# -*- coding: utf-8 -*-
# pylint: disable=undefined-all-variable
"""Sandbox provider plugin package for CoPaw.

Provides a SandboxProvider Protocol and concrete implementations:
  - E2BSandboxProvider: routes execution into E2B sandbox
  - AgentscopeSandboxProvider: routes via sandbox-manager API
  - NullSandboxProvider: no-op, all tool calls run locally
"""

from .provider import SandboxProvider
from .null_provider import NullSandboxProvider

__all__ = [
    "SandboxProvider",
    "E2BSandboxProvider",
    "AgentscopeSandboxProvider",
    "AgentscopeSandboxHandle",
    "NullSandboxProvider",
]


def __getattr__(name: str):
    """Lazy-load providers to avoid import-time circular issues."""
    if name == "E2BSandboxProvider":
        from .e2b_provider import E2BSandboxProvider

        return E2BSandboxProvider
    if name in ("AgentscopeSandboxProvider", "AgentscopeSandboxHandle"):
        from .agentscope_provider import (
            AgentscopeSandboxProvider,
            AgentscopeSandboxHandle,
        )

        if name == "AgentscopeSandboxProvider":
            return AgentscopeSandboxProvider
        return AgentscopeSandboxHandle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

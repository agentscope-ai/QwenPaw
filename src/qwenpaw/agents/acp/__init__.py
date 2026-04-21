# -*- coding: utf-8 -*-
"""ACP client and server exports."""

from __future__ import annotations

from .core import (
    ACPConfigurationError,
    ACPProtocolError,
    ACPSessionError,
    ACPTransportError,
    ACPErrors,
    PermissionResolution,
    SuspendedPermission,
)
from .service import ACPService, get_acp_service, init_acp_service

__all__ = [
    "ACPErrors",
    "ACPConfigurationError",
    "ACPProtocolError",
    "ACPSessionError",
    "ACPTransportError",
    "ACPService",
    "QwenPawACPAgent",
    "get_acp_service",
    "init_acp_service",
    "PermissionResolution",
    "run_qwenpaw_agent",
    "SuspendedPermission",
]


def __getattr__(name: str):
    """Lazily import ACP server bindings.

    The web app imports ACP helper packages transitively during startup. The
    ACP server implementation depends on the optional third-party `acp`
    package, so importing it eagerly turns that optional feature into a hard
    startup requirement.
    """
    if name in {"QwenPawACPAgent", "run_qwenpaw_agent"}:
        from .server import QwenPawACPAgent, run_qwenpaw_agent

        globals().update(
            {
                "QwenPawACPAgent": QwenPawACPAgent,
                "run_qwenpaw_agent": run_qwenpaw_agent,
            },
        )
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

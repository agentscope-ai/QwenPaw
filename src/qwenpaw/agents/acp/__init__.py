# -*- coding: utf-8 -*-
"""ACP client and server exports.

NOTE(as2-migration): ``.server`` and ``.service`` still import from
``agentscope_runtime.engine.schemas.agent_schemas`` and are not yet ported
to agentscope 2.0.  Eagerly importing them here would break every consumer
of ``qwenpaw.agents.acp`` — including ``delegate_external_agent``
which only needs ``tool_adapter``.  We expose ``QwenPawACPAgent`` /
``run_qwenpaw_agent`` / ``ACPService`` / ``*_acp_service`` via ``__getattr__``
so the heavy modules load only when actually requested.
"""
from importlib import import_module
from typing import Any

from .core import (
    ACPConfigurationError,
    ACPProtocolError,
    ACPSessionError,
    ACPTransportError,
    ACPErrors,
    SuspendedPermission,
)

_LAZY_EXPORTS = {
    "QwenPawACPAgent": ".server",
    "run_qwenpaw_agent": ".server",
    "ACPService": ".service",
    "close_acp_service": ".service",
    "get_acp_service": ".service",
    "init_acp_service": ".service",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


# pylint: disable=undefined-all-variable
# Names below from "ACPService" onward are resolved by ``__getattr__`` above
# (lazy-loaded from ``.server`` / ``.service``).  pylint's static analysis
# can't follow ``__getattr__`` so it flags them as undefined; runtime is
# fine — verified by ``from qwenpaw.agents.acp import ACPService`` working.
__all__ = [
    "ACPErrors",
    "ACPConfigurationError",
    "ACPProtocolError",
    "ACPSessionError",
    "ACPTransportError",
    "ACPService",
    "QwenPawACPAgent",
    "close_acp_service",
    "get_acp_service",
    "init_acp_service",
    "run_qwenpaw_agent",
    "SuspendedPermission",
]

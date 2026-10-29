# -*- coding: utf-8 -*-
"""Explicit shared-environment plugin execution, independent of loaders."""

from .process import (
    PluginLaunchSpec,
    PluginProcess,
    StopResult,
    ProcessError,
    CallUnknown,
)
from .models import PluginIdentity
from .runtime import PluginContext
from .framing import FramedTransport, FramingLimits
from .rpc import RpcPeer, RpcLimits

__all__ = [
    "PluginLaunchSpec",
    "PluginProcess",
    "PluginIdentity",
    "PluginContext",
    "StopResult",
    "ProcessError",
    "CallUnknown",
    "FramedTransport",
    "FramingLimits",
    "RpcPeer",
    "RpcLimits",
]

# -*- coding: utf-8 -*-
"""Generic PawApp readiness and setup contracts."""

from .contracts import (
    PrepareResult,
    ReadinessResult,
    SetupEntryDescriptor,
    SetupOpenAction,
    SetupRequest,
    SetupRequirement,
    SetupResult,
    SuggestedValue,
)
from .registry import SetupCheckRegistration, SetupEntryRegistration
from .runtime import SetupCoordinator
from .store import SetupRecord, SetupStore

__all__ = [
    "PrepareResult",
    "ReadinessResult",
    "SetupCheckRegistration",
    "SetupCoordinator",
    "SetupEntryDescriptor",
    "SetupEntryRegistration",
    "SetupOpenAction",
    "SetupRequest",
    "SetupRequirement",
    "SetupResult",
    "SetupRecord",
    "SetupStore",
    "SuggestedValue",
]

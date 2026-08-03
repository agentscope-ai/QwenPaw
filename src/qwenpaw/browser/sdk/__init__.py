# -*- coding: utf-8 -*-
"""Public Unified Browser SDK contracts."""

from typing import TYPE_CHECKING

from .contracts import (
    ActionLevel,
    ActionResult,
    CapabilityVerdict,
    Condition,
    Context,
    ContextVersion,
    Coverage,
    CoverageGap,
    CurrentSurface,
    DialogInfo,
    FileChooserInfo,
    FrameLocatorView,
    NetworkResponse,
    Observation,
    ObservedElement,
    Owner,
    PageRef,
    ReadResult,
    ReadSegment,
    RegionSummary,
    ResourceHandle,
    SessionStatus,
    Variant,
)

__all__ = [
    "ActionLevel",
    "ActionResult",
    "CapabilityVerdict",
    "Condition",
    "Context",
    "ContextVersion",
    "Coverage",
    "CoverageGap",
    "CurrentSurface",
    "DialogInfo",
    "FileChooserInfo",
    "FrameLocatorView",
    "NetworkResponse",
    "Observation",
    "ObservedElement",
    "Owner",
    "PageRef",
    "ReadResult",
    "ReadSegment",
    "RegionSummary",
    "ResourceHandle",
    "SessionStatus",
    "Variant",
]


if TYPE_CHECKING:
    from .facade import Browser
    from .page import Page


def __getattr__(name: str) -> object:
    """Lazily expose Browser/Page from the SDK package path (PEP 562)."""
    if name == "Browser":
        from .facade import Browser as _Browser

        return _Browser
    if name == "Page":
        from .page import Page as _Page

        return _Page
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

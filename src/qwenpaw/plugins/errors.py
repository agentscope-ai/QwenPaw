# -*- coding: utf-8 -*-
"""Stable errors raised by the opt-in plugin SDK."""


class SDKError(RuntimeError):
    """Base error for SDK contract violations."""


class SDKCompatibilityError(SDKError):
    """The declared SDK version or capability is unavailable."""


class SDKAccessError(SDKError):
    """The requested object is outside this caller's authorized scope."""


class SDKRestartRequiredError(SDKCompatibilityError):
    """A dependency change requires a fresh host process."""


class StaleContextError(SDKError):
    """An operation belongs to a stopped or superseded plugin instance."""


class ResourceError(SDKError):
    """A managed resource cannot be created or stopped safely."""


class ToolInputError(SDKError):
    """Tool arguments do not satisfy the declared schema."""

# -*- coding: utf-8 -*-
"""Error types for ACP runtime integration."""


class ACPError(Exception):
    """Base class for ACP runtime errors."""


class ACPTransportError(ACPError):
    """Raised when the harness transport fails."""


class ACPProtocolError(ACPError):
    """Raised when ACP protocol data is invalid."""


class ACPConfigurationError(ACPError):
    """Raised when ACP configuration is missing or invalid."""


class ACPPermissionError(ACPError):
    """Raised when a permission request cannot be completed."""

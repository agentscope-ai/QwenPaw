# -*- coding: utf-8 -*-
"""ACP shared definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...config.config import ACPAgentConfig, ACPConfig
from ...exceptions import (
    ACPConfigurationError,
    ACPError,
    ACPProtocolError,
    ACPSessionError,
    ACPTransportError,
)

ACPErrors = ACPError

__all__ = [
    "ACPAgentConfig",
    "ACPConfig",
    "ACPError",
    "ACPErrors",
    "ACPConfigurationError",
    "ACPTransportError",
    "ACPProtocolError",
    "ACPSessionError",
    "SuspendedPermission",
]


@dataclass
class SuspendedPermission:
    payload: dict[str, Any]
    options: list[dict[str, Any]]
    agent: str
    tool_name: str
    tool_kind: str
    target: str | None = None
    action: str | None = None
    summary: str | None = None
    command: str | None = None
    paths: list[str] = field(default_factory=list)
    requires_user_confirmation: bool = True

# -*- coding: utf-8 -*-
"""Minimal ACP shared definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class ACPErrors(Exception):
    def __init__(self, message: str, *, agent: Optional[str] = None):
        super().__init__(message)
        self.agent = agent


class ACPConfigurationError(ACPErrors):
    pass


class ACPTransportError(ACPErrors):
    pass


class ACPProtocolError(ACPErrors):
    pass


class ACPSessionError(ACPErrors):
    pass


@dataclass
class PermissionResolution:
    result: dict[str, Any] | None = None
    suspended: "SuspendedPermission" | None = None


@dataclass
class SuspendedPermission:
    request_id: Any
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

# -*- coding: utf-8 -*-
"""Typed results for host-owned, temporary channel management workers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal, Mapping, TypeAlias

from .events import JSONValue
from .resources import ResourceScope


@dataclass(frozen=True)
class ChannelManagementRequest:
    request_id: str
    plugin_id: str
    workspace_id: str
    channel_key: str
    operation: Literal["qrcode.fetch", "qrcode.poll", "connection.verify"]
    config: Mapping[str, JSONValue] = field(repr=False)
    resources: ResourceScope
    deadline: float
    options: Mapping[str, str] = field(default_factory=dict)
    continuation: str | None = field(default=None, repr=False)
    verification_level: Literal["reachability", "credentials"] | None = None

    def remaining_timeout(self) -> float:
        return max(0.0, self.deadline - asyncio.get_running_loop().time())

    def check_cancelled(self) -> None:
        task = asyncio.current_task()
        if self.resources.closed or (task and task.cancelling()):
            raise asyncio.CancelledError
        if not self.remaining_timeout():
            raise TimeoutError("Channel management deadline exceeded")


@dataclass(frozen=True)
class ChannelQRCode:
    scan_url: str
    continuation: str = field(repr=False)
    expires_in_seconds: int | None = None


@dataclass(frozen=True)
class ChannelAuthorization:
    status: str
    credentials: Mapping[str, str] = field(default_factory=dict, repr=False)
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelVerification:
    level: Literal["reachability", "credentials"]
    verdict: Literal["passed", "failed", "unsupported"]
    reason_code: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChannelManagementFailure:
    reason_code: str
    unsupported: bool = False


ChannelManagementResult: TypeAlias = (
    ChannelQRCode
    | ChannelAuthorization
    | ChannelVerification
    | ChannelManagementFailure
)

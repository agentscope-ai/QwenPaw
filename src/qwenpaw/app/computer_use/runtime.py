# -*- coding: utf-8 -*-
"""Host-provided Computer Use runtime capability and turn context."""

from __future__ import annotations

import json
import os
import socket
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from typing import ClassVar

_PIPE_ENV = "QWENPAW_COMPUTER_USE_PIPE"
_CAPABILITY_ENV = "QWENPAW_COMPUTER_USE_CAPABILITY"
_PROTOCOL_ENV = "QWENPAW_COMPUTER_USE_PROTOCOL"
_CONTROL_HOST_ENV = "QWENPAW_COMPUTER_USE_CONTROL_HOST"
_CONTROL_PORT_ENV = "QWENPAW_COMPUTER_USE_CONTROL_PORT"
_CONTROL_TOKEN_ENV = "QWENPAW_COMPUTER_USE_CONTROL_TOKEN"
_CONTROL_PROTOCOL_ENV = "QWENPAW_COMPUTER_USE_CONTROL_PROTOCOL"
_CONTROL_MAX_MESSAGE_BYTES = 4096
# The desktop host answers acquire only after it has spawned the helper
# process; the first spawn after an install or update can be slowed by
# antivirus scanning, so budget for that worst case rather than the
# steady-state round trip.
_CONTROL_TIMEOUT_SECONDS = 10.0
_current_turn_id: ContextVar[str | None] = ContextVar(
    "computer_use_turn_id",
    default=None,
)


@dataclass(frozen=True)
class RuntimeCapability:
    """Opaque desktop-host capability used only by the controlled client."""

    _pipe_name: str
    _secret: str
    protocol_version: int


@dataclass(frozen=True)
class _ControlEndpoint:
    host: str
    port: int
    token: str
    protocol_version: int


class HostRuntimeProvider:
    """Obtain a desktop-host capability without exposing it to tool inputs."""

    _capability: ClassVar[RuntimeCapability | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def get_capability(cls) -> RuntimeCapability | None:
        """Return an already-issued desktop capability, if any."""
        with cls._lock:
            return cls._capability or _environment_capability()

    @classmethod
    def acquire_capability(cls) -> RuntimeCapability | None:
        """Ask the desktop host to start the helper and issue a capability."""
        with cls._lock:
            capability = cls._capability or _environment_capability()
            if capability is not None:
                return capability
            control = _control_endpoint()
            if control is None:
                return None
            capability = _request_capability(control)
            if capability is not None:
                cls._capability = capability
            return capability

    @classmethod
    def is_available(cls) -> bool:
        """Whether this process can obtain a compatible desktop capability."""
        return (
            cls.get_capability() is not None or _control_endpoint() is not None
        )


def _environment_capability() -> RuntimeCapability | None:
    """Return a capability injected when the backend was restarted."""
    pipe_name = os.environ.get(_PIPE_ENV, "").strip()
    secret = os.environ.get(_CAPABILITY_ENV, "").strip()
    raw_version = os.environ.get(_PROTOCOL_ENV, "1").strip()
    try:
        protocol_version = int(raw_version)
    except ValueError:
        return None
    if not pipe_name or not secret or protocol_version < 1:
        return None
    return RuntimeCapability(pipe_name, secret, protocol_version)


def _control_endpoint() -> _ControlEndpoint | None:
    host = os.environ.get(_CONTROL_HOST_ENV, "").strip()
    token = os.environ.get(_CONTROL_TOKEN_ENV, "").strip()
    try:
        port = int(os.environ.get(_CONTROL_PORT_ENV, ""))
        protocol_version = int(os.environ.get(_CONTROL_PROTOCOL_ENV, "1"))
    except ValueError:
        return None
    if (
        host != "127.0.0.1"
        or not 0 < port < 65536
        or not token
        or protocol_version != 1
    ):
        return None
    return _ControlEndpoint(host, port, token, protocol_version)


def _request_capability(control: _ControlEndpoint) -> RuntimeCapability | None:
    request = {
        "protocol_version": control.protocol_version,
        "token": control.token,
        "action": "acquire",
    }
    try:
        with socket.create_connection(
            (control.host, control.port),
            timeout=_CONTROL_TIMEOUT_SECONDS,
        ) as connection:
            connection.settimeout(_CONTROL_TIMEOUT_SECONDS)
            with connection.makefile("rwb") as stream:
                stream.write(
                    json.dumps(request, separators=(",", ":")).encode("utf-8"),
                )
                stream.write(b"\n")
                stream.flush()
                payload = stream.readline(_CONTROL_MAX_MESSAGE_BYTES + 1)
        if not payload or len(payload) > _CONTROL_MAX_MESSAGE_BYTES:
            return None
        response = json.loads(payload)
    except (OSError, ValueError):
        return None
    if not isinstance(response, dict) or response.get("ok") is not True:
        return None
    pipe_name = response.get("pipe_name")
    secret = response.get("capability")
    version = response.get("protocol_version")
    if (
        not isinstance(pipe_name, str)
        or not isinstance(secret, str)
        or version != control.protocol_version
    ):
        return None
    if not pipe_name or not secret:
        return None
    return RuntimeCapability(pipe_name, secret, version)


def set_current_computer_use_turn_id(turn_id: str | None) -> None:
    """Bind one native Computer Use turn to the active agent dispatch."""
    _current_turn_id.set(turn_id)


def get_current_computer_use_turn_id() -> str | None:
    """Return the turn id assigned by request setup for this dispatch."""
    return _current_turn_id.get()

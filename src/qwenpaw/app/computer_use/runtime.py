# -*- coding: utf-8 -*-
"""Host-provided Computer Use runtime capability and turn context."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from typing import ClassVar

# Platforms with a native helper. The helper is a Rust binary built and staged
# only for these two; on anything else there is nothing to talk to, however the
# host is configured.
_SUPPORTED_PLATFORMS = frozenset({"win32", "darwin"})

_PIPE_ENV = "QWENPAW_COMPUTER_USE_PIPE"
_CAPABILITY_ENV = "QWENPAW_COMPUTER_USE_CAPABILITY"
_PROTOCOL_ENV = "QWENPAW_COMPUTER_USE_PROTOCOL"
_CONTROL_HOST_ENV = "QWENPAW_COMPUTER_USE_CONTROL_HOST"
_CONTROL_PORT_ENV = "QWENPAW_COMPUTER_USE_CONTROL_PORT"
_CONTROL_TOKEN_ENV = "QWENPAW_COMPUTER_USE_CONTROL_TOKEN"
# Request/response contract shared by the plugin and native helper.
COMPUTER_USE_PROTOCOL_VERSION = 1
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
class RuntimeStatus:
    """The separate preconditions for using Computer Use in this process.

    Reported apart rather than as one boolean so a caller can tell a machine
    that will never support the feature from a desktop host that simply has not
    offered a capability yet, and can say which it is.
    """

    supported_platform: bool
    host_reachable: bool

    @property
    def available(self) -> bool:
        """Whether a capability could actually be obtained here."""
        return self.supported_platform and self.host_reachable


@dataclass(frozen=True)
class RuntimeCapability:
    """Opaque desktop-host capability used only by the controlled client."""

    _pipe_name: str
    _secret: str
    protocol_version: int

    def names_same_endpoint(self, other: "RuntimeCapability") -> bool:
        """Whether both capabilities point at the same helper endpoint.

        Comparing whole capabilities would compare secrets too, and asking
        callers to read the endpoint would make it part of the surface this
        type exists to keep closed. Reading it from a peer of the same type
        keeps it closed.
        """
        # pylint: disable=protected-access
        return self._pipe_name == other._pipe_name


@dataclass(frozen=True)
class _ControlEndpoint:
    host: str
    port: int
    token: str


class HostRuntimeProvider:
    """Obtain a desktop-host capability without exposing it to tool inputs."""

    _capability: ClassVar[RuntimeCapability | None] = None
    # Set once the capability handed over in the environment has proven dead,
    # so
    # it stops being returned in place of asking the host for a live one.
    _environment_spent: ClassVar[bool] = False
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def get_capability(cls) -> RuntimeCapability | None:
        """Return an already-issued desktop capability, if any."""
        with cls._lock:
            return cls._live_capability()

    @classmethod
    def acquire_capability(cls) -> RuntimeCapability | None:
        """Ask the desktop host to start the helper and issue a capability."""
        with cls._lock:
            capability = cls._live_capability()
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
    def invalidate_capability(cls, capability: RuntimeCapability) -> None:
        """Forget a capability whose endpoint has gone away.

        A helper that crashes leaves its pipe or socket behind as a name that
        connects to nothing. Without this the cached capability would be handed
        out for the rest of the process, so one crash disabled Computer Use
        until the backend restarted -- even though the desktop host notices the
        dead child and will issue a new capability when asked.

        Only the named endpoint is forgotten, so a capability that has already
        been refreshed by another caller survives. Invalidating one that was in
        fact healthy costs a single round trip to the host, which answers with
        the same endpoint again.
        """
        with cls._lock:
            cached = cls._capability
            if cached is not None and cached.names_same_endpoint(capability):
                cls._capability = None
            injected = _environment_capability()
            if injected is not None and injected.names_same_endpoint(
                capability,
            ):
                # The environment value is a bootstrap handed over at spawn;
                # once its endpoint is gone it must stop being an answer, or it
                # would be returned again on the next call.
                cls._environment_spent = True

    @classmethod
    def _live_capability(cls) -> RuntimeCapability | None:
        """The capability to use, ignoring any endpoint known to be dead.

        The caller holds ``_lock``.
        """
        if cls._capability is not None:
            return cls._capability
        if cls._environment_spent:
            return None
        return _environment_capability()

    @classmethod
    def status(cls) -> RuntimeStatus:
        """Report each precondition for obtaining a capability separately."""
        return RuntimeStatus(
            supported_platform=sys.platform in _SUPPORTED_PLATFORMS,
            host_reachable=(
                cls.get_capability() is not None
                or _control_endpoint() is not None
            ),
        )

    @classmethod
    def is_available(cls) -> bool:
        """Whether this process can obtain a compatible desktop capability.

        A reachable host is not enough. The desktop shell offers a control
        endpoint on every platform it runs on, while the helper is only built
        for Windows and macOS -- so taking the endpoint as the whole answer
        registered a tool on Linux that could never do anything but report the
        runtime unavailable, once per call.
        """
        return cls.status().available


def _environment_capability() -> RuntimeCapability | None:
    """Return a capability injected when the backend was restarted."""
    pipe_name = os.environ.get(_PIPE_ENV, "").strip()
    secret = os.environ.get(_CAPABILITY_ENV, "").strip()
    raw_version = os.environ.get(
        _PROTOCOL_ENV,
        str(COMPUTER_USE_PROTOCOL_VERSION),
    ).strip()
    try:
        protocol_version = int(raw_version)
    except ValueError:
        return None
    if (
        not pipe_name
        or not secret
        or protocol_version != COMPUTER_USE_PROTOCOL_VERSION
    ):
        return None
    return RuntimeCapability(pipe_name, secret, protocol_version)


def _control_endpoint() -> _ControlEndpoint | None:
    host = os.environ.get(_CONTROL_HOST_ENV, "").strip()
    token = os.environ.get(_CONTROL_TOKEN_ENV, "").strip()
    try:
        port = int(os.environ.get(_CONTROL_PORT_ENV, ""))
    except ValueError:
        return None
    if host != "127.0.0.1" or not 0 < port < 65536 or not token:
        return None
    return _ControlEndpoint(host, port, token)


def _request_capability(control: _ControlEndpoint) -> RuntimeCapability | None:
    response = _request_control(control, {"action": "acquire"})
    if response is None or response.get("ok") is not True:
        return None
    pipe_name = response.get("pipe_name")
    secret = response.get("capability")
    if not isinstance(pipe_name, str) or not isinstance(secret, str):
        return None
    if not pipe_name or not secret:
        return None
    return RuntimeCapability(pipe_name, secret, COMPUTER_USE_PROTOCOL_VERSION)


def _request_control(
    control: _ControlEndpoint,
    fields: dict[str, object],
) -> dict[str, object] | None:
    """Exchange one bounded request with the authenticated desktop host."""
    request = {"token": control.token, **fields}
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
    if not isinstance(response, dict):
        return None
    return response


def set_current_computer_use_turn_id(turn_id: str | None) -> None:
    """Bind one native Computer Use turn to the active agent dispatch."""
    _current_turn_id.set(turn_id)


def get_current_computer_use_turn_id() -> str | None:
    """Return the turn id assigned by request setup for this dispatch."""
    return _current_turn_id.get()

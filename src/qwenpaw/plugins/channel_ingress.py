# -*- coding: utf-8 -*-
"""Host-routed platform callbacks; platform signature checks remain in drivers."""

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Mapping
from urllib.parse import urlencode

from .errors import SDKError


@dataclass(frozen=True)
class ChannelIngressRoute:
    """An exact method and relative path under this channel's host namespace."""

    method: Literal[
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
        "WEBSOCKET",
    ]
    path: str


@dataclass(frozen=True)
class ChannelIngressSpec:
    """A plugin-owned loopback listener, forwarded only while this worker lives.

    Bind the listener under ch.ingress.path and register it with ch.resources.
    public_base_url is the deployment origin, without a path or credentials.
    A starting listener may have port zero; ready listeners require a bound port.
    """

    host: str
    port: int
    protocol: Literal["http", "ws", "http+ws"] = "http+ws"
    readiness: Literal["starting", "ready", "degraded", "stopped"] = "ready"
    public_base_url: str | None = None


@dataclass(frozen=True)
class ChannelIngressBinding:
    """A current host routing acknowledgment; not a platform authorization."""

    host_port: int
    paths: tuple[str, ...]
    public_base_url: str | None
    _query_key: str = field(repr=False)
    _selector: str = field(repr=False)
    _verify: Callable[[Mapping[str, str]], str] = field(
        repr=False,
        compare=False,
    )
    _guard: Callable[[], None] = field(repr=False, compare=False)

    def url(self, path: str) -> str:
        """Build a declared callback URL including this workspace's selector."""
        self._guard()
        if path not in self.paths or self.public_base_url is None:
            raise SDKError("A declared path and public origin are required")
        return (
            self.public_base_url.rstrip("/")
            + path
            + "?"
            + urlencode({self._query_key: self._selector})
        )

    def verify(self, headers: Mapping[str, str]) -> str:
        """Verify host forwarding and return the original URL for platform checks.

        Call this before the platform's signature/secret check. This alone
        proves only that the host forwarded a request, not who sent it.
        """
        self._guard()
        return self._verify(headers)


@dataclass(frozen=True)
class ChannelIngress:
    """Register one listener for the channel's statically declared routes."""

    path: str
    _register: Callable[
        [ChannelIngressSpec],
        Awaitable[ChannelIngressBinding],
    ] = field(
        repr=False,
    )
    _update: Callable[
        [ChannelIngressSpec],
        Awaitable[ChannelIngressBinding],
    ] = field(
        repr=False,
    )
    _close: Callable[[], Awaitable[None]] = field(repr=False)

    async def register(
        self,
        spec: ChannelIngressSpec,
    ) -> ChannelIngressBinding:
        return await self._register(spec)

    async def update(self, spec: ChannelIngressSpec) -> ChannelIngressBinding:
        return await self._update(spec)

    async def close(self) -> None:
        """Withdraw routing and wait for host forwards to close, not the listener."""
        await self._close()

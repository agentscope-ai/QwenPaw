# -*- coding: utf-8 -*-
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_LOOPBACK_HOSTNAMES = {"localhost"}
# Wildcard bind addresses mapped to the loopback address of the same
# address family.  Winsock rejects ``INADDR_ANY`` and ``in6addr_any`` as
# ``connect`` targets with ``WSAEADDRNOTAVAIL``, and a socket bound to
# ``::`` is not reachable over IPv4, so the families must not be mixed.
_WILDCARD_PROBE_HOSTS = {
    "": "127.0.0.1",
    "0.0.0.0": "127.0.0.1",
    "::": "::1",
}


def probe_host_for_bind_host(host: str) -> str:
    """Return an address that can be connected to for a bind address.

    A wildcard bind address accepts connections but cannot be used as a
    ``connect`` target, so callers probing their own listener must use
    the loopback address of the matching family instead.  A blank host
    binds every interface of both families, so it maps to IPv4 loopback.
    Any other host is returned unchanged, minus whitespace and IPv6 URL
    brackets.
    """
    normalized = host.strip().strip("[]")
    return _WILDCARD_PROBE_HOSTS.get(normalized, normalized)


def is_loopback_host(host: str) -> bool:
    """Return True when *host* is localhost or a loopback IP address."""
    normalized = host.strip().strip("[]").lower().rstrip(".")
    if normalized in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def is_loopback_url(url: str) -> bool:
    """Return True when *url* targets a localhost or loopback address."""
    return is_loopback_host(urlparse(url).hostname or "")


def trust_env_for_url(url: str) -> bool:
    """Return whether httpx should trust proxy/cert env vars for *url*."""
    return not is_loopback_url(url)

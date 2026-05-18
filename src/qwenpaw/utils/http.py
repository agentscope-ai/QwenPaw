# -*- coding: utf-8 -*-
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_LOOPBACK_HOSTNAMES = {"localhost"}


def is_loopback_url(url: str) -> bool:
    """Return True when *url* targets a localhost or loopback address."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def trust_env_for_url(url: str) -> bool:
    """Return whether httpx should trust proxy/cert env vars for *url*."""
    return not is_loopback_url(url)

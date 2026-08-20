# -*- coding: utf-8 -*-
"""Tests for Hub authentication abuse protection."""

from fastapi import Request

from qwenpaw.hub.access_security import HubAccessSecurity
from qwenpaw.hub.config import AccessSecurityConfig, RateLimitConfig


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "headers": headers,
            "client": (peer, 1234),
        },
    )


def test_forwarded_address_requires_trusted_proxy() -> None:
    security = HubAccessSecurity(
        AccessSecurityConfig(trusted_proxy_ips=["10.0.0.0/8"]),
    )

    assert security.client_ip(_request("192.0.2.1", "203.0.113.7")) == (
        "192.0.2.1"
    )
    assert security.client_ip(_request("10.0.0.2", "203.0.113.7")) == (
        "203.0.113.7"
    )


def test_forwarded_address_ignores_spoofed_leftmost_value() -> None:
    security = HubAccessSecurity(
        AccessSecurityConfig(trusted_proxy_ips=["10.0.0.0/8"]),
    )

    request = _request(
        "10.0.0.2",
        "127.0.0.1, 203.0.113.7, 10.0.0.3",
    )

    assert security.client_ip(request) == "203.0.113.7"


def test_invalid_forwarded_chain_falls_back_to_direct_peer() -> None:
    security = HubAccessSecurity(
        AccessSecurityConfig(trusted_proxy_ips=["10.0.0.0/8"]),
    )

    request = _request("10.0.0.2", "203.0.113.7, invalid")

    assert security.client_ip(request) == "10.0.0.2"


def test_blacklist_supports_addresses_and_networks() -> None:
    security = HubAccessSecurity(
        AccessSecurityConfig(ip_blacklist=["192.0.2.4", "2001:db8::/64"]),
    )

    assert security.is_blacklisted("192.0.2.4") is True
    assert security.is_blacklisted("2001:db8::5") is True
    assert security.is_blacklisted("192.0.2.5") is False


def test_rate_limit_blocks_then_expires() -> None:
    now = 100.0
    security = HubAccessSecurity(
        AccessSecurityConfig(
            login_rate_limit=RateLimitConfig(
                max_attempts=2,
                window_seconds=60,
                block_seconds=30,
            ),
        ),
        clock=lambda: now,
    )

    security.record_attempt("login", "192.0.2.4")
    security.record_attempt("login", "192.0.2.4")
    assert security.retry_after("login", "192.0.2.4") == 30
    now = 131.0
    assert security.retry_after("login", "192.0.2.4") is None

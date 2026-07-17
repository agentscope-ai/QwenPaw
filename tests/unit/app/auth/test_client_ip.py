# -*- coding: utf-8 -*-
"""Unit tests for the auth bypass fix (NVDB-TEMP-CAIVD-2026671557).

Validates that _resolve_client_ip and _should_skip_auth correctly handle
trusted proxy verification and XFF right-to-left parsing.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.app.auth import (
    _ip_in_networks,
    _normalize_ip,
    _parse_networks,
    _resolve_client_ip,
    _warned_untrusted_ips,
)


@pytest.fixture(autouse=True)
def _clear_warn_state():
    """Reset per-IP warning dedup between tests."""
    _warned_untrusted_ips.clear()
    yield
    _warned_untrusted_ips.clear()


# ---------------------------------------------------------------------------
# _normalize_ip
# ---------------------------------------------------------------------------


class TestNormalizeIp:
    def test_plain_ipv4(self):
        assert _normalize_ip("1.2.3.4") == "1.2.3.4"

    def test_ipv4_with_port(self):
        assert _normalize_ip("1.2.3.4:8080") == "1.2.3.4"

    def test_plain_ipv6(self):
        assert _normalize_ip("::1") == "::1"

    def test_bracketed_ipv6_with_port(self):
        assert _normalize_ip("[::1]:443") == "::1"

    def test_ipv6_with_zone_id(self):
        assert _normalize_ip("fe80::1%eth0") == "fe80::1"

    def test_empty_string(self):
        assert _normalize_ip("") is None

    def test_garbage(self):
        assert _normalize_ip("not-an-ip") is None


# ---------------------------------------------------------------------------
# _ip_in_networks
# ---------------------------------------------------------------------------


class TestIpInNetworks:
    def test_exact_match(self):
        nets = _parse_networks(["10.0.0.1"])
        assert _ip_in_networks("10.0.0.1", nets) is True

    def test_no_match(self):
        nets = _parse_networks(["10.0.0.1"])
        assert _ip_in_networks("1.2.3.4", nets) is False

    def test_cidr_match(self):
        nets = _parse_networks(["172.17.0.0/16"])
        assert _ip_in_networks("172.17.0.5", nets) is True

    def test_cidr_no_match(self):
        nets = _parse_networks(["172.17.0.0/16"])
        assert _ip_in_networks("192.168.1.1", nets) is False

    def test_ipv6_cidr(self):
        nets = _parse_networks(["fd00::/64"])
        assert _ip_in_networks("fd00::5", nets) is True

    def test_invalid_ip(self):
        nets = _parse_networks(["10.0.0.0/8"])
        assert _ip_in_networks("garbage", nets) is False

    def test_empty_networks(self):
        assert _ip_in_networks("10.0.0.1", []) is False


# ---------------------------------------------------------------------------
# _resolve_client_ip
# ---------------------------------------------------------------------------


def _make_request(
    client_host: str,
    xff: str = "",
    real_ip: str = "",
) -> MagicMock:
    """Create a mock Request with specified client and headers."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = client_host

    headers = {}
    if xff:
        headers["x-forwarded-for"] = xff
    if real_ip:
        headers["x-real-ip"] = real_ip
    request.headers = headers
    return request


def _make_config_return(trusted_proxies=None, allow_no_auth_hosts=None):
    """Build the (config, networks) tuple that _get_config_cached returns."""
    config = MagicMock()
    config.security.trusted_proxies = trusted_proxies or []
    config.security.allow_no_auth_hosts = allow_no_auth_hosts or [
        "127.0.0.1",
        "::1",
    ]
    networks = _parse_networks(config.security.trusted_proxies)
    return (config, networks)


class TestResolveClientIp:
    """Core vulnerability regression tests."""

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_vuln_regression_xff_spoofed_no_trusted_proxies(self, mock_cfg):
        """CVE scenario: attacker spoofs XFF, no trusted_proxies configured."""
        mock_cfg.return_value = _make_config_return(trusted_proxies=[])
        req = _make_request("1.2.3.4", xff="127.0.0.1")
        assert _resolve_client_ip(req) == "1.2.3.4"

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_vuln_regression_real_ip_spoofed_no_trusted_proxies(
        self,
        mock_cfg,
    ):
        """Attacker spoofs X-Real-IP, no trusted_proxies configured."""
        mock_cfg.return_value = _make_config_return(trusted_proxies=[])
        req = _make_request("1.2.3.4", real_ip="127.0.0.1")
        assert _resolve_client_ip(req) == "1.2.3.4"

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_single_trusted_proxy(self, mock_cfg):
        """Legitimate single-tier proxy: returns real client IP from XFF."""
        mock_cfg.return_value = _make_config_return(
            trusted_proxies=["10.0.0.1"],
        )
        req = _make_request("10.0.0.1", xff="8.8.8.8")
        assert _resolve_client_ip(req) == "8.8.8.8"

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_attacker_prepends_loopback_in_xff(self, mock_cfg):
        """Attacker prepends 127.0.0.1 in XFF; right-to-left skips trusted."""
        mock_cfg.return_value = _make_config_return(
            trusted_proxies=["10.0.0.1"],
        )
        req = _make_request("10.0.0.1", xff="127.0.0.1, 8.8.8.8")
        assert _resolve_client_ip(req) == "8.8.8.8"

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_all_xff_are_trusted_falls_back_to_direct(self, mock_cfg):
        """When all XFF entries are trusted proxies, fall back to direct_ip."""
        mock_cfg.return_value = _make_config_return(
            trusted_proxies=["10.0.0.1", "10.0.0.2"],
        )
        req = _make_request("10.0.0.1", xff="10.0.0.2")
        # All XFF are trusted → falls through to X-Real-IP or direct_ip
        assert _resolve_client_ip(req) == "10.0.0.1"

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_cidr_trusted_proxy(self, mock_cfg):
        """CIDR matching for trusted proxy (Docker/K8s scenarios)."""
        mock_cfg.return_value = _make_config_return(
            trusted_proxies=["172.17.0.0/16"],
        )
        req = _make_request("172.17.0.5", xff="8.8.8.8")
        assert _resolve_client_ip(req) == "8.8.8.8"

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_direct_not_trusted_ignores_xff(self, mock_cfg):
        """Direct connection NOT in trusted_proxies: XFF is ignored."""
        mock_cfg.return_value = _make_config_return(
            trusted_proxies=["10.0.0.1"],
        )
        req = _make_request("1.2.3.4", xff="127.0.0.1")
        assert _resolve_client_ip(req) == "1.2.3.4"

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_unparseable_xff_token_stops_parsing(self, mock_cfg):
        """Junk tokens in XFF abort parsing to prevent injection."""
        mock_cfg.return_value = _make_config_return(
            trusted_proxies=["10.0.0.1"],
        )
        req = _make_request(
            "10.0.0.1",
            xff="127.0.0.1, junk_token, 10.0.0.1",
        )
        # Reversed: 10.0.0.1 (trusted, skip) → junk_token (None → break)
        # Falls through to X-Real-IP or direct_ip
        assert _resolve_client_ip(req) == "10.0.0.1"

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_x_real_ip_used_when_xff_empty(self, mock_cfg):
        """X-Real-IP is used when no XFF and direct is trusted."""
        mock_cfg.return_value = _make_config_return(
            trusted_proxies=["10.0.0.1"],
        )
        req = _make_request("10.0.0.1", real_ip="203.0.113.7")
        assert _resolve_client_ip(req) == "203.0.113.7"

    @patch("qwenpaw.app.auth._get_config_cached")
    def test_localhost_direct_no_proxy_headers(self, mock_cfg):
        """Local CLI: direct loopback, no proxy headers → returns 127.0.0.1."""
        mock_cfg.return_value = _make_config_return(trusted_proxies=[])
        req = _make_request("127.0.0.1")
        assert _resolve_client_ip(req) == "127.0.0.1"


# ---------------------------------------------------------------------------
# _should_skip_auth defense-in-depth
# ---------------------------------------------------------------------------


class TestShouldSkipAuthDefenseInDepth:
    """Verify loopback whitelist requires direct peer also be loopback."""

    @patch("qwenpaw.app.auth._get_config_cached")
    @patch("qwenpaw.app.auth.is_auth_enabled", return_value=True)
    @patch("qwenpaw.app.auth.has_registered_users", return_value=True)
    def test_loopback_direct_passes(self, _a, _b, mock_cfg):
        from qwenpaw.app.auth import AuthMiddleware  # noqa: F811

        mock_cfg.return_value = _make_config_return()
        req = _make_request("127.0.0.1")
        req.url = MagicMock()
        req.url.path = "/api/protected"
        req.method = "GET"
        # pylint: disable=protected-access
        assert AuthMiddleware._should_skip_auth(req) is True

    @patch("qwenpaw.app.auth._get_config_cached")
    @patch("qwenpaw.app.auth.is_auth_enabled", return_value=True)
    @patch("qwenpaw.app.auth.has_registered_users", return_value=True)
    def test_loopback_via_proxy_blocked(self, _a, _b, mock_cfg):
        """test resolved IP=127.0.0.1 but direct peer is external."""
        from qwenpaw.app.auth import AuthMiddleware  # noqa: F811

        mock_cfg.return_value = _make_config_return(
            trusted_proxies=["10.0.0.1"],
            allow_no_auth_hosts=["127.0.0.1", "::1"],
        )
        # Simulate: trusted proxy forwards XFF=127.0.0.1
        # _resolve_client_ip would return 127.0.0.1 from XFF
        # But _should_skip_auth checks direct peer
        req = _make_request("10.0.0.1", xff="127.0.0.1")
        req.url = MagicMock()
        req.url.path = "/api/protected"
        req.method = "GET"
        # pylint: disable=protected-access
        assert AuthMiddleware._should_skip_auth(req) is False

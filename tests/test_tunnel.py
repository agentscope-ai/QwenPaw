# -*- coding: utf-8 -*-
"""Tests for Cloudflare Tunnel driver (mocked subprocess)."""
from copaw.tunnel.cloudflare import _URL_RE, TunnelInfo


class TestUrlPattern:
    def test_matches_trycloudflare_url(self):
        line = "2024-01-15 INF |  https://abc-def-123.trycloudflare.com"
        m = _URL_RE.search(line)
        assert m is not None
        assert m.group(0) == "https://abc-def-123.trycloudflare.com"

    def test_no_match_on_other_urls(self):
        line = "https://example.com/some/path"
        m = _URL_RE.search(line)
        assert m is None

    def test_matches_various_subdomains(self):
        for subdomain in [
            "hello-world",
            "abc123",
            "my-tunnel-name-456",
            "a",
        ]:
            url = f"https://{subdomain}.trycloudflare.com"
            m = _URL_RE.search(url)
            assert m is not None, f"Failed for subdomain: {subdomain}"


class TestTunnelInfo:
    def test_dataclass_creation(self):
        from datetime import datetime, timezone

        info = TunnelInfo(
            public_url="https://test.trycloudflare.com",
            public_wss_url="wss://test.trycloudflare.com",
            started_at=datetime.now(timezone.utc),
            pid=12345,
        )
        assert info.public_url == "https://test.trycloudflare.com"
        assert info.public_wss_url == "wss://test.trycloudflare.com"
        assert info.pid == 12345

    def test_wss_url_derivation(self):
        url = "https://my-tunnel.trycloudflare.com"
        wss = url.replace("https://", "wss://")
        assert wss == "wss://my-tunnel.trycloudflare.com"

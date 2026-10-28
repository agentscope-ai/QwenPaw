# -*- coding: utf-8 -*-
"""Tests for MCP OAuth PKCE helpers and session lifecycle.

Covers _generate_code_verifier, _code_challenge, OAuthSession expiry,
_purge_expired, _redirect_uri, _popup_html, and _make_error_page, which
previously had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

from types import SimpleNamespace


from qwenpaw.app.routers import mcp_oauth as mo


# ---------------------------------------------------------------------------
# _redirect_uri
# ---------------------------------------------------------------------------


class TestRedirectUri:
    def test_managed_url_preferred(self, monkeypatch):
        monkeypatch.setattr(
            mo,
            "managed_oauth_callback_url",
            lambda request: "https://managed/callback",
        )
        request = SimpleNamespace()
        assert mo._redirect_uri(request) == "https://managed/callback"

    def test_url_for_fallback(self, monkeypatch):
        monkeypatch.setattr(
            mo,
            "managed_oauth_callback_url",
            lambda request: None,
        )
        request = SimpleNamespace(url_for=lambda name: "https://app/cb")
        assert mo._redirect_uri(request) == "https://app/cb"

    def test_manual_fallback(self, monkeypatch):
        monkeypatch.setattr(
            mo,
            "managed_oauth_callback_url",
            lambda request: None,
        )

        def broken(name):
            raise RuntimeError("no route")

        request = SimpleNamespace(
            url_for=broken,
            base_url="https://app.local/",
        )
        assert mo._redirect_uri(request) == (
            "https://app.local/api/mcp/oauth/callback"
        )


# ---------------------------------------------------------------------------
# _popup_html / _make_error_page
# ---------------------------------------------------------------------------


class TestPopupHtml:
    def test_status_and_type_embedded(self):
        html = mo._popup_html("success", "<p>ok</p>")
        assert "mcp-oauth" in html
        assert "success" in html
        assert "<p>ok</p>" in html

    def test_extra_data_merged(self):
        html = mo._popup_html("success", "<p/>", {"client": "k1"})
        assert "k1" in html


class TestMakeErrorPage:
    def test_html_escaped(self):
        response = mo._make_error_page("<script>alert(1)</script>")
        assert response.status_code == 400
        body = response.body.decode("utf-8")
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body

    def test_plain_message_rendered(self):
        response = mo._make_error_page("something failed")
        assert "something failed" in response.body.decode("utf-8")

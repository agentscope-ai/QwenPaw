# -*- coding: utf-8 -*-
"""Tests for MCP OAuth PKCE helpers and session lifecycle.

Covers _generate_code_verifier, _code_challenge, OAuthSession expiry,
_purge_expired, _redirect_uri, _popup_html, and _make_error_page, which
previously had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import base64
import hashlib
import time
from types import SimpleNamespace

import pytest

from qwenpaw.app.routers import mcp_oauth as mo


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


class TestPkce:
    def test_verifier_is_urlsafe_base64(self):
        verifier = mo._generate_code_verifier()
        assert verifier
        # must be valid urlsafe base64 without padding
        assert "=" not in verifier
        assert "+" not in verifier
        assert "/" not in verifier

    def test_verifier_random_each_call(self):
        assert mo._generate_code_verifier() != mo._generate_code_verifier()

    def test_code_challenge_is_s256_of_verifier(self):
        verifier = "test-verifier-abc123"
        expected = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest(),
            )
            .rstrip(b"=")
            .decode()
        )
        assert mo._code_challenge(verifier) == expected

    def test_code_challenge_urlsafe(self):
        challenge = mo._code_challenge("v" * 64)
        assert "+" not in challenge
        assert "/" not in challenge


# ---------------------------------------------------------------------------
# OAuthSession / _purge_expired
# ---------------------------------------------------------------------------


def _session(created_ago: float = 0.0):
    session = mo.OAuthSession(
        agent_id="a1",
        client_key="k1",
        code_verifier="verifier",
        client_id="client",
        auth_endpoint="https://auth",
        token_endpoint="https://token",
        redirect_uri="https://cb",
        scope="read",
    )
    session.created_at = time.monotonic() - created_ago
    return session


class TestOAuthSession:
    def test_fresh_session_not_expired(self):
        assert _session().is_expired() is False

    def test_old_session_expired(self):
        assert _session(created_ago=mo._TTL_SECONDS + 1).is_expired() is True

    def test_attributes_stored(self):
        session = _session()
        assert session.agent_id == "a1"
        assert session.client_key == "k1"
        assert session.scope == "read"


class TestPurgeExpired:
    @pytest.fixture(autouse=True)
    def _clean_store(self):
        mo._state_store.clear()
        yield
        mo._state_store.clear()

    def test_removes_only_expired(self):
        mo._state_store["fresh"] = _session()
        mo._state_store["old"] = _session(created_ago=mo._TTL_SECONDS + 1)
        mo._purge_expired()
        assert "fresh" in mo._state_store
        assert "old" not in mo._state_store

    def test_empty_store_safe(self):
        mo._purge_expired()  # must not raise
        assert mo._state_store == {}


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

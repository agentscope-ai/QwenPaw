# -*- coding: utf-8 -*-
"""Tests for MiniMax OAuth pure functions."""

from copaw.cli._oauth import (
    _to_base64url,
    _generate_pkce,
    _get_endpoints,
    OAuthResult,
)


class TestToBase64url:
    """Tests for _to_base64url function."""

    def test_to_base64url_empty(self):
        """Test empty bytes returns empty string."""
        result = _to_base64url(b"")
        assert result == ""

    def test_to_base64url_hello(self):
        """Test 'hello' encodes to expected base64url value."""
        result = _to_base64url(b"hello")
        assert result == "aGVsbG8"

    def test_to_base64url_no_padding(self):
        """Test result contains no padding characters."""
        result = _to_base64url(b"abc")
        assert "=" not in result


class TestGeneratePkce:
    """Tests for _generate_pkce function."""

    def test_generate_pkce_returns_tuple(self):
        """Test function returns a 3-tuple."""
        result = _generate_pkce()
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_generate_pkce_verifier_length(self):
        """Test PKCE verifier has correct length (43 chars for 32 bytes)."""
        verifier, _, _ = _generate_pkce()
        assert len(verifier) == 43
        # Should be base64url safe (A-Za-z0-9_-), no padding
        assert "=" not in verifier

    def test_generate_pkce_challenge_length(self):
        """Test PKCE challenge has correct length (43 chars for SHA256)."""
        _, challenge, _ = _generate_pkce()
        assert len(challenge) == 43
        # Should be base64url safe (A-Za-z0-9_-), no padding
        assert "=" not in challenge

    def test_generate_pkce_verifier_challenge_relationship(self):
        """Test challenge is SHA256(verifier) in base64url."""
        import hashlib

        verifier, challenge, _ = _generate_pkce()
        expected_challenge = _to_base64url(
            hashlib.sha256(verifier.encode("ascii")).digest(),
        )
        assert challenge == expected_challenge

    def test_generate_pkce_state_length(self):
        """Test state has correct length (22 chars for 16 bytes)."""
        _, _, state = _generate_pkce()
        assert len(state) == 22

    def test_generate_pkce_uniqueness(self):
        """Test multiple calls produce different results."""
        result1 = _generate_pkce()
        result2 = _generate_pkce()
        assert result1 != result2


class TestGetEndpoints:
    """Tests for _get_endpoints function."""

    def test_get_endpoints_cn(self):
        """Test China region endpoints."""
        code_endpoint, token_endpoint, client_id = _get_endpoints("cn")
        assert "minimaxi.com" in code_endpoint
        assert "minimaxi.com" in token_endpoint
        assert "/oauth/code" in code_endpoint
        assert "/oauth/token" in token_endpoint
        assert client_id == "78257093-7e40-4613-99e0-527b14b39113"

    def test_get_endpoints_global(self):
        """Test International region endpoints."""
        code_endpoint, token_endpoint, client_id = _get_endpoints("global")
        assert "minimax.io" in code_endpoint
        assert "minimax.io" in token_endpoint
        assert "/oauth/code" in code_endpoint
        assert "/oauth/token" in token_endpoint
        assert client_id == "78257093-7e40-4613-99e0-527b14b39113"


class TestOAuthResult:
    """Tests for OAuthResult class."""

    def test_oauth_result_init(self):
        """Test OAuthResult initializes with correct attributes."""
        result = OAuthResult(
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            expires_at=1743465600,
        )
        assert result.access_token == "test-access-token"
        assert result.refresh_token == "test-refresh-token"
        assert result.expires_at == 1743465600
        assert result.is_oauth is True

    def test_oauth_result_to_dict(self):
        """Test OAuthResult.to_dict returns correct structure."""
        result = OAuthResult(
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            expires_at=1743465600,
        )
        d = result.to_dict()
        assert d["access_token"] == "test-access-token"
        assert d["refresh_token"] == "test-refresh-token"
        assert d["token_expires_at"] == 1743465600
        assert d["is_oauth"] is True

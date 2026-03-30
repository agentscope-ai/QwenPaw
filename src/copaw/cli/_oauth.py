# -*- coding: utf-8 -*-
"""MiniMax OAuth authentication using Device Code Flow with PKCE."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import webbrowser

import httpx

MINIMAX_OAUTH_CONFIG = {
    "cn": {
        "base_url": "https://api.minimaxi.com",
        "client_id": "78257093-7e40-4613-99e0-527b14b39113",
    },
    "global": {
        "base_url": "https://api.minimax.io",
        "client_id": "78257093-7e40-4613-99e0-527b14b39113",
    },
}

MINIMAX_OAUTH_SCOPE = "group_id profile model.completion"
MINIMAX_OAUTH_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:user_code"


def _to_base64url(data: bytes) -> str:
    """Convert bytes to base64url string without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_pkce() -> tuple[str, str, str]:
    """Generate PKCE verifier, challenge, and state.

    Returns:
        Tuple of (verifier, challenge, state)
    """
    verifier = _to_base64url(secrets.token_bytes(32))
    challenge_hash = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = _to_base64url(challenge_hash)
    state = _to_base64url(secrets.token_bytes(16))
    return verifier, challenge, state


def _get_endpoints(
    region: str,
) -> tuple[str, str, str]:
    """Get OAuth endpoints for the given region.

    Args:
        region: "cn" or "global"

    Returns:
        Tuple of (code_endpoint, token_endpoint, client_id)
    """
    config = MINIMAX_OAUTH_CONFIG[region]
    base_url = config["base_url"]
    return (
        f"{base_url}/oauth/code",
        f"{base_url}/oauth/token",
        config["client_id"],
    )


def _request_oauth_code(
    challenge: str,
    state: str,
    region: str,
) -> dict:
    """Request OAuth authorization code.

    Args:
        challenge: PKCE code challenge
        state: Random state for CSRF protection
        region: "cn" or "global"

    Returns:
        Dict containing user_code, verification_uri, expires_in, interval
    """
    code_endpoint, _, client_id = _get_endpoints(region)

    data = {
        "response_type": "code",
        "client_id": client_id,
        "scope": MINIMAX_OAUTH_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            code_endpoint,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )

    if not response.is_success:
        raise RuntimeError(
            f"MiniMax OAuth authorization failed: "
            f"{response.status_code} {response.text}",
        )

    payload = response.json()
    if not payload.get("user_code") or not payload.get("verification_uri"):
        raise RuntimeError(
            "MiniMax OAuth returned incomplete payload "
            "(missing user_code or verification_uri)",
        )
    if payload.get("state") != state:
        raise RuntimeError(
            "MiniMax OAuth state mismatch: possible CSRF attack",
        )

    return payload


def _poll_oauth_token(
    user_code: str,
    verifier: str,
    region: str,
) -> dict:
    """Poll for OAuth token.

    Args:
        user_code: The user code from authorization
        verifier: PKCE code verifier
        region: "cn" or "global"

    Returns:
        Dict containing access_token, refresh_token, expires_in
    """
    _, token_endpoint, client_id = _get_endpoints(region)

    data = {
        "grant_type": MINIMAX_OAUTH_GRANT_TYPE,
        "client_id": client_id,
        "user_code": user_code,
        "code_verifier": verifier,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            token_endpoint,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )

    if not response.is_success:
        return {
            "status": "error",
            "message": f"Token request failed: {response.status_code}",
        }

    payload = response.json()

    if payload.get("status") == "error":
        return {
            "status": "error",
            "message": payload.get("status_msg", "Unknown error"),
        }

    if payload.get("status") != "success":
        return {"status": "pending"}

    if not payload.get("access_token") or not payload.get("refresh_token"):
        return {"status": "error", "message": "Incomplete token payload"}

    return {
        "status": "success",
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "expires_in": payload.get("expired_in", 0),
    }


class OAuthResult:
    """Result of a successful OAuth authentication."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: int,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.is_oauth = True

    def to_dict(self) -> dict:
        """Convert to dict for storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expires_at": self.expires_at,
            "is_oauth": True,
        }


def login_minimax_oauth(
    region: str,
    open_browser: bool = True,
) -> OAuthResult:
    """Authenticate to MiniMax via OAuth Device Code Flow.

    Args:
        region: "cn" for China, "global" for international
        open_browser: Whether to automatically open the verification URL

    Returns:
        OAuthResult with access_token, refresh_token, and expires_at
    """
    verifier, challenge, state = _generate_pkce()

    auth_data = _request_oauth_code(challenge, state, region)
    verification_uri = auth_data["verification_uri"]
    user_code = auth_data["user_code"]
    expires_in = auth_data.get("expired_in", 0)
    interval = auth_data.get("interval", 2000) / 1000.0  # Convert to seconds

    print("\n=== MiniMax OAuth Authentication ===")
    print(f"Open {verification_uri}")
    print(f"And enter the code: {user_code}")
    print(f"Expires in: {expires_in} seconds\n")

    if open_browser:
        webbrowser.open(verification_uri)

    expire_time = (
        time.time() + expires_in / 1000.0 if expires_in else time.time() + 300
    )

    while time.time() < expire_time:
        result = _poll_oauth_token(user_code, verifier, region)

        if result["status"] == "success":
            expires_at = int(time.time() + result["expires_in"] / 1000.0)
            return OAuthResult(
                access_token=result["access_token"],
                refresh_token=result["refresh_token"],
                expires_at=expires_at,
            )

        if result["status"] == "error":
            raise RuntimeError(f"OAuth failed: {result['message']}")

        print("Waiting for authorization... (press Ctrl+C to cancel)")
        time.sleep(interval)

    raise RuntimeError("OAuth timed out before authorization completed")

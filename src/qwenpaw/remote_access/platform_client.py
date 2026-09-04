# -*- coding: utf-8 -*-
"""Client for Platform Relay node enrollment."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

import httpx

from .identity import RelayKeyPair


PLATFORM_OAUTH_CLIENT_ID = "agentscope-platform-cli"
RELAY_PROTOCOL_VERSION = 1


class RelayPlatformError(RuntimeError):
    """An error returned by the Platform Relay control plane."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class EnrollmentToken:
    """Short-lived token used exactly once to register a Relay node."""

    token: str
    expires_in: int
    credential_generation: int
    dpop_nonce: str


@dataclass(frozen=True, slots=True)
class RegisteredNode:
    """Long-lived key-bound identity returned after node registration."""

    node_id: str
    credential: str
    dpop_nonce: str
    credential_generation: int


@dataclass(frozen=True, slots=True)
class RelayConnectTicket:
    """Single-use proof-bound ticket for one Node WSS connection."""

    token: str
    websocket_url: str
    expires_in: int
    dpop_nonce: str
    next_credential_dpop_nonce: str


@dataclass(frozen=True, slots=True)
class RelayPairingTicket:
    """Short-lived Relay QR data issued to an authenticated Node."""

    token: str
    node_id: str
    qwenpaw_id: str
    node_public_key_thumbprint: str
    expires_in: int
    dpop_nonce: str
    next_credential_dpop_nonce: str


class PlatformRelayClient:
    """Perform PKCE OAuth and one-time Node enrollment."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = _normalize_platform_url(base_url)
        self._client = client

    async def register_node(
        self,
        *,
        qwenpaw_id: str,
        name: str,
        enrollment: EnrollmentToken,
        key_pair: RelayKeyPair,
    ) -> RegisteredNode:
        """Consume an enrollment token and create the persistent Node."""
        path = "/api/v1/qwenpaw-relay/nodes"
        target = f"{self.base_url}{path}"
        proof = key_pair.create_proof(
            "POST",
            target,
            enrollment.token,
            enrollment.dpop_nonce,
        )
        payload = await self._post(
            path,
            json={
                "qwenpaw_id": qwenpaw_id,
                "name": name,
                "protocol_version": RELAY_PROTOCOL_VERSION,
            },
            headers={
                "Authorization": f"RelayEnrollment {enrollment.token}",
                "DPoP": proof,
            },
        )
        node = payload.get("node")
        if not isinstance(node, Mapping):
            raise RelayPlatformError(
                "invalid_response",
                "Platform did not return the registered Node",
                status_code=502,
            )
        return RegisteredNode(
            node_id=_required_string(node, "id"),
            credential=_required_string(payload, "node_credential"),
            dpop_nonce=_required_string(payload, "dpop_nonce"),
            credential_generation=_required_int(
                node,
                "credential_generation",
            ),
        )

    async def exchange_oauth_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> tuple[str, str | None]:
        """Exchange a localhost PKCE callback code for Platform tokens."""
        payload = await self._post_raw(
            "/api/cli/v1/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": PLATFORM_OAUTH_CLIENT_ID,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        access_token = _required_string(payload, "access_token")
        refresh_token = payload.get("refresh_token")
        return (
            access_token,
            refresh_token if isinstance(refresh_token, str) else None,
        )

    async def create_oauth_enrollment(
        self,
        *,
        access_token: str,
        qwenpaw_id: str,
        name: str,
        key_pair: RelayKeyPair,
    ) -> EnrollmentToken:
        """Create a one-time Node enrollment as the OAuth user."""
        payload = await self._post(
            "/api/v1/qwenpaw-relay/oauth-enrollments",
            json={
                "qwenpaw_id": qwenpaw_id,
                "name": name,
                "protocol_version": RELAY_PROTOCOL_VERSION,
                "public_key_jwk": key_pair.public_jwk(),
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if payload.get("token_type") != "RelayEnrollment":
            raise RelayPlatformError(
                "invalid_response",
                "Platform returned an unsupported enrollment token",
                status_code=502,
            )
        return EnrollmentToken(
            token=_required_string(payload, "enrollment_token"),
            expires_in=_required_int(payload, "expires_in"),
            credential_generation=_required_int(
                payload,
                "credential_generation",
            ),
            dpop_nonce=_required_string(payload, "dpop_nonce"),
        )

    async def revoke_oauth_refresh_token(self, refresh_token: str) -> None:
        """Revoke the transient refresh token after Node registration."""
        await self._post_raw(
            "/api/cli/v1/oauth/revoke",
            json={
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            },
        )

    async def create_node_connect_ticket(
        self,
        registered: RegisteredNode,
        key_pair: RelayKeyPair,
    ) -> RelayConnectTicket:
        """Rotate the Node nonce and obtain a single-use WSS ticket."""
        path = "/api/v1/qwenpaw-relay/node/connect-tickets"
        target = f"{self.base_url}{path}"
        proof = key_pair.create_proof(
            "POST",
            target,
            registered.credential,
            registered.dpop_nonce,
        )
        payload = await self._post(
            path,
            json={},
            headers={
                "Authorization": f"RelayNode {registered.credential}",
                "DPoP": proof,
            },
        )
        if payload.get("role") != "node":
            raise RelayPlatformError(
                "invalid_response",
                "Platform returned a ticket for the wrong Relay role",
                status_code=502,
            )
        websocket_url = _required_string(payload, "websocket_url")
        _validate_relay_websocket_url(websocket_url)
        return RelayConnectTicket(
            token=_required_string(payload, "connect_ticket"),
            websocket_url=websocket_url,
            expires_in=_required_int(payload, "expires_in"),
            dpop_nonce=_required_string(payload, "dpop_nonce"),
            next_credential_dpop_nonce=_required_string(
                payload,
                "next_credential_dpop_nonce",
            ),
        )

    async def create_node_pairing_ticket(
        self,
        registered: RegisteredNode,
        key_pair: RelayKeyPair,
    ) -> RelayPairingTicket:
        """Create a short-lived QR ticket and rotate the Node nonce."""
        path = "/api/v1/qwenpaw-relay/node/pairing-tickets"
        target = f"{self.base_url}{path}"
        proof = key_pair.create_proof(
            "POST",
            target,
            registered.credential,
            registered.dpop_nonce,
        )
        payload = await self._post(
            path,
            json={},
            headers={
                "Authorization": f"RelayNode {registered.credential}",
                "DPoP": proof,
            },
        )
        if _required_int(payload, "protocol_version") != 1:
            raise RelayPlatformError(
                "invalid_response",
                "Platform returned an unsupported pairing protocol",
                status_code=502,
            )
        return RelayPairingTicket(
            token=_required_string(payload, "pairing_ticket"),
            node_id=_required_string(payload, "node_id"),
            qwenpaw_id=_required_string(payload, "qwenpaw_id"),
            node_public_key_thumbprint=_required_string(
                payload,
                "node_public_key_thumbprint",
            ),
            expires_in=_required_int(payload, "expires_in"),
            dpop_nonce=_required_string(payload, "dpop_nonce"),
            next_credential_dpop_nonce=_required_string(
                payload,
                "next_node_dpop_nonce",
            ),
        )

    async def _post(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        body = await self._post_raw(path, json=json, headers=headers)
        data = body.get("data")
        if not isinstance(data, Mapping):
            raise RelayPlatformError(
                "invalid_response",
                "Platform Relay response is malformed",
                status_code=502,
            )
        return data

    async def _post_raw(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
        )
        try:
            response = await client.post(
                f"{self.base_url}{path}",
                json=dict(json),
                headers=dict(headers or {}),
            )
        except httpx.HTTPError as exc:
            raise RelayPlatformError(
                "platform_unavailable",
                "Platform Relay is temporarily unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        body = _response_object(response)
        if not response.is_success:
            raise RelayPlatformError(
                str(body.get("code") or "platform_error"),
                str(body.get("message") or "Platform Relay request failed"),
                status_code=response.status_code,
                retryable=body.get("retryable") is True,
            )
        return body


def _normalize_platform_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Platform URL must be an HTTP(S) origin")
    if parsed.username or parsed.password:
        raise ValueError("Platform URL must be an HTTP(S) origin")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Platform URL must be an HTTP(S) origin")
    if parsed.scheme == "http" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("Platform URL must use HTTPS")
    netloc = parsed.netloc.lower()
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))


def _validate_relay_websocket_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"wss", "ws"} or not parsed.hostname:
        raise RelayPlatformError(
            "invalid_response",
            "Platform returned an invalid Relay WebSocket URL",
            status_code=502,
        )
    if parsed.scheme == "ws" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RelayPlatformError(
            "invalid_response",
            "Platform returned an insecure Relay WebSocket URL",
            status_code=502,
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RelayPlatformError(
            "invalid_response",
            "Platform returned an invalid Relay WebSocket URL",
            status_code=502,
        )


def _response_object(response: httpx.Response) -> Mapping[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise RelayPlatformError(
            "invalid_response",
            "Platform Relay returned a non-JSON response",
            status_code=502,
        ) from exc
    if not isinstance(body, Mapping):
        raise RelayPlatformError(
            "invalid_response",
            "Platform Relay response is malformed",
            status_code=502,
        )
    return body


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise RelayPlatformError(
            "invalid_response",
            f"Platform Relay response is missing {name}",
            status_code=502,
        )
    return value


def _required_int(payload: Mapping[str, Any], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RelayPlatformError(
            "invalid_response",
            f"Platform Relay response is missing {name}",
            status_code=502,
        )
    return value

# -*- coding: utf-8 -*-
"""Tests for Platform Relay PKCE OAuth enrollment."""
from __future__ import annotations

import httpx
import pytest

from qwenpaw.remote_access import (
    PlatformRelayClient,
    RelayKeyPair,
    RelayPlatformError,
)


def _response(data: dict) -> dict:
    return {"request_id": "request-1", "data": data}


@pytest.mark.asyncio
async def test_pkce_oauth_registers_key_bound_node() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 900,
                    "token_type": "Bearer",
                },
            )
        if request.url.path.endswith("/oauth-enrollments"):
            return httpx.Response(
                200,
                json=_response(
                    {
                        "token_type": "RelayEnrollment",
                        "enrollment_token": "enrollment-token",
                        "expires_in": 60,
                        "credential_generation": 1,
                        "dpop_nonce": "enrollment-nonce",
                    },
                ),
            )
        if request.url.path.endswith("/oauth/revoke"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(
            200,
            json=_response(
                {
                    "node": {
                        "id": "a9a34d17-66d7-4604-b8e8-35e514e3ea10",
                        "credential_generation": 1,
                    },
                    "quota": {"used": 1, "limit": 1},
                    "node_credential": "qprn_v1.node.secret",
                    "dpop_nonce": "node-nonce",
                },
            ),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PlatformRelayClient(
            "https://platform.test/",
            client=http_client,
        )
        key_pair = RelayKeyPair.generate()
        access_token, refresh_token = await client.exchange_oauth_code(
            code="authorization-code",
            redirect_uri="http://127.0.0.1:8088/callback/nonce123",
            code_verifier="v" * 64,
        )
        enrollment = await client.create_oauth_enrollment(
            access_token=access_token,
            qwenpaw_id="paw-1",
            name="Office Paw",
            key_pair=key_pair,
        )
        node = await client.register_node(
            qwenpaw_id="paw-1",
            name="Office Paw",
            enrollment=enrollment,
            key_pair=key_pair,
        )
        await client.revoke_oauth_refresh_token(refresh_token or "")

    assert node.credential == "qprn_v1.node.secret"
    assert requests[1].headers["Authorization"] == "Bearer access-token"
    assert requests[2].headers["Authorization"] == (
        "RelayEnrollment enrollment-token"
    )
    assert requests[2].headers["DPoP"].count(".") == 2


@pytest.mark.asyncio
async def test_node_connect_ticket_rotates_nonce_without_url_leak() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_response(
                {
                    "connect_ticket": "qprc_v1.secret",
                    "websocket_url": "wss://relay.platform.test/relay/v1/node",
                    "role": "node",
                    "expires_in": 30,
                    "dpop_nonce": "connect-nonce",
                    "next_credential_dpop_nonce": "next-node-nonce",
                },
            ),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = PlatformRelayClient(
            "https://platform.test",
            client=http_client,
        )
        from qwenpaw.remote_access import RegisteredNode

        ticket = await client.create_node_connect_ticket(
            RegisteredNode(
                node_id="node-1",
                credential="qprn_v1.node.secret",
                dpop_nonce="node-nonce",
                credential_generation=1,
            ),
            RelayKeyPair.generate(),
        )

    assert ticket.next_credential_dpop_nonce == "next-node-nonce"
    assert "qprc_v1.secret" not in ticket.websocket_url
    assert requests[0].headers["Authorization"] == (
        "RelayNode qprn_v1.node.secret"
    )
    assert requests[0].headers["DPoP"].count(".") == 2


@pytest.mark.asyncio
async def test_node_pairing_ticket_is_bound_to_registered_identity() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_response(
                {
                    "pairing_ticket": "qprp_v1.secret",
                    "node_id": "node-1",
                    "qwenpaw_id": "paw-1",
                    "node_public_key_thumbprint": "thumbprint",
                    "protocol_version": 1,
                    "expires_in": 120,
                    "dpop_nonce": "pairing-nonce",
                    "next_node_dpop_nonce": "next-node-nonce",
                },
            ),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = PlatformRelayClient(
            "https://platform.test",
            client=http_client,
        )
        from qwenpaw.remote_access import RegisteredNode

        ticket = await client.create_node_pairing_ticket(
            RegisteredNode(
                node_id="node-1",
                credential="qprn_v1.node.secret",
                dpop_nonce="node-nonce",
                credential_generation=1,
            ),
            RelayKeyPair.generate(),
        )

    assert ticket.token == "qprp_v1.secret"
    assert ticket.next_credential_dpop_nonce == "next-node-nonce"
    assert requests[0].url.path.endswith("/node/pairing-tickets")
    assert requests[0].headers["Authorization"] == (
        "RelayNode qprn_v1.node.secret"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://platform.example.com",
        "https://user@platform.example.com",
        "https://platform.example.com/path",
    ],
)
def test_platform_origin_rejects_insecure_or_ambiguous_url(url: str) -> None:
    with pytest.raises(ValueError):
        PlatformRelayClient(url)

# -*- coding: utf-8 -*-
"""API coverage for local Platform Relay pairing metadata."""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app.routers import remote_access
from qwenpaw.remote_access import RelayEnrollmentStatus, RelayPairingTicket


@pytest.mark.asyncio
async def test_pairing_endpoint_returns_versioned_qr_json(
    monkeypatch,
) -> None:
    class Enrollment:
        async def status(self) -> RelayEnrollmentStatus:
            return RelayEnrollmentStatus(
                status="connected",
                platform_url="https://platform.test",
                qwenpaw_id="paw-1",
                node_id="node-1",
            )

    class Connection:
        async def create_pairing_ticket(self) -> RelayPairingTicket:
            return RelayPairingTicket(
                token="qprt_v1_secret",
                node_id="node-1",
                qwenpaw_id="paw-1",
                node_public_key_thumbprint="thumbprint",
                expires_in=120,
                dpop_nonce="pairing-nonce",
                next_credential_dpop_nonce="next-node-nonce",
            )

    monkeypatch.setattr(remote_access, "_service", Enrollment())
    monkeypatch.setattr(
        remote_access,
        "_connection_service",
        Connection(),
    )
    app = FastAPI()
    app.include_router(remote_access.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/remote-access/platform/pairing")

    assert response.status_code == 200
    payload = response.json()
    assert {
        key: payload[key]
        for key in (
            "type",
            "v",
            "issuer",
            "node_id",
            "qwenpaw_id",
            "pairing_ticket",
            "node_public_key_thumbprint",
            "dpop_nonce",
            "protocol_version",
            "expires_in",
        )
    } == {
        "type": "qwenpaw.relay.pairing",
        "v": 2,
        "issuer": "https://platform.test",
        "node_id": "node-1",
        "qwenpaw_id": "paw-1",
        "pairing_ticket": "qprt_v1_secret",
        "node_public_key_thumbprint": "thumbprint",
        "dpop_nonce": "pairing-nonce",
        "protocol_version": 1,
        "expires_in": 120,
    }
    assert payload["qrcode_img"]
    assert payload["qr_payload"].startswith("{")
    assert payload["expires_at"] > 0


@pytest.mark.asyncio
async def test_pairing_endpoint_rejects_unregistered_node(
    monkeypatch,
) -> None:
    class Enrollment:
        async def status(self) -> RelayEnrollmentStatus:
            return RelayEnrollmentStatus(status="not_connected")

    monkeypatch.setattr(remote_access, "_service", Enrollment())
    app = FastAPI()
    app.include_router(remote_access.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/remote-access/platform/pairing")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_oauth_callback_registers_node_and_returns_to_console(
    monkeypatch,
) -> None:
    calls: list[dict[str, str]] = []

    class Enrollment:
        async def complete_oauth(self, **kwargs) -> RelayEnrollmentStatus:
            calls.append(kwargs)
            return RelayEnrollmentStatus(status="connected", node_id="node-1")

    class Supervisor:
        def start(self) -> None:
            calls.append({"supervisor": "started"})

    monkeypatch.setattr(remote_access, "_service", Enrollment())
    monkeypatch.setattr(remote_access, "_supervisor", Supervisor())
    app = FastAPI()
    app.include_router(remote_access.callback_router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8088",
    ) as client:
        response = await client.get(
            "/callback/nonce-123?state=state-123&code=code-123",
        )

    assert response.status_code == 200
    assert "QwenPaw 已连接" in response.text
    assert calls == [
        {
            "nonce": "nonce-123",
            "state_value": "state-123",
            "code": "code-123",
        },
        {"supervisor": "started"},
    ]

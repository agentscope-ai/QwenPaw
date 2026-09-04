# -*- coding: utf-8 -*-
"""Tests for the short-lived mobile pairing ticket store."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.pairing import PairingTicketStore
import qwenpaw.app.routers.auth as auth_module


def test_pairing_ticket_is_single_use() -> None:
    """A successful redemption must consume the ticket atomically."""
    store = PairingTicketStore()
    ticket, _ = store.create("mobile-user")

    assert store.redeem(ticket) == "mobile-user"
    assert store.redeem(ticket) is None


def test_pairing_ticket_expires() -> None:
    """Expired tickets must be rejected and removed."""
    now = [1000.0]
    store = PairingTicketStore(clock=lambda: now[0], ttl_seconds=10)
    ticket, expires_at = store.create("mobile-user")
    assert expires_at == 1010

    now[0] = 1010.0
    assert store.redeem(ticket) is None


def test_invalid_secret_does_not_consume_ticket() -> None:
    """An invalid guess must not invalidate another user's ticket."""
    store = PairingTicketStore()
    ticket, _ = store.create("mobile-user")
    ticket_id, _ = ticket.split(".", 1)

    assert store.redeem(f"{ticket_id}.wrong-secret") is None
    assert store.redeem(ticket) == "mobile-user"


def test_pairing_endpoint_creates_redeemable_qr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public wire contract must support one successful redemption."""
    monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: False)
    app = FastAPI()
    app.include_router(auth_module.router)
    client = TestClient(app)

    created = client.post(
        "/auth/pairing",
        json={"base_url": "https://paw.example.com/"},
    )
    assert created.status_code == 200
    body = created.json()
    assert len(body["qrcode_img"]) > 100
    parsed = urlsplit(body["pairing_uri"])
    assert parsed.scheme == "qwenpaw"
    assert parsed.hostname == "pair"
    query = parse_qs(parsed.query)
    assert query["base_url"] == ["https://paw.example.com"]

    redeemed = client.post(
        "/auth/pairing/redeem",
        json={"ticket": query["ticket"][0]},
    )
    assert redeemed.status_code == 200
    assert redeemed.json() == {"token": "", "username": ""}
    repeated = client.post(
        "/auth/pairing/redeem",
        json={"ticket": query["ticket"][0]},
    )
    assert repeated.status_code == 401


def test_pairing_endpoint_requires_auth_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unauthenticated caller cannot mint a mobile pairing ticket."""
    monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_module, "verify_token", lambda token: None)
    app = FastAPI()
    app.include_router(auth_module.router)

    response = TestClient(app).post(
        "/auth/pairing",
        json={"base_url": "https://paw.example.com"},
    )
    assert response.status_code == 401


def test_pairing_issues_persistent_revocable_mobile_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authenticated binding remains valid until explicit revocation."""
    expiry_seconds: list[int] = []
    monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        auth_module,
        "verify_token",
        lambda token: "mobile-user" if token == "console-token" else None,
    )

    def create_token(username: str, expiry: int) -> str:
        assert username == "mobile-user"
        expiry_seconds.append(expiry)
        return "mobile-token"

    monkeypatch.setattr(auth_module, "create_token", create_token)
    app = FastAPI()
    app.include_router(auth_module.router)
    client = TestClient(app)

    created = client.post(
        "/auth/pairing",
        headers={"Authorization": "Bearer console-token"},
        json={"base_url": "https://paw.example.com"},
    )
    query = parse_qs(urlsplit(created.json()["pairing_uri"]).query)
    redeemed = client.post(
        "/auth/pairing/redeem",
        json={"ticket": query["ticket"][0]},
    )

    assert redeemed.json() == {
        "token": "mobile-token",
        "username": "mobile-user",
    }
    assert expiry_seconds == [0]

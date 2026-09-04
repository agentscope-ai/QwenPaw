# -*- coding: utf-8 -*-
"""Tests for local Platform Relay enrollment orchestration."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from qwenpaw.remote_access import (
    EnrollmentToken,
    RegisteredNode,
    RelayEnrollmentService,
    RelayNodeStore,
)


class _FakeClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def exchange_oauth_code(self, **_kwargs):
        return "access-token", "refresh-token"

    async def create_oauth_enrollment(self, **_kwargs) -> EnrollmentToken:
        return EnrollmentToken(
            token="enrollment",
            expires_in=60,
            credential_generation=1,
            dpop_nonce="enrollment-nonce",
        )

    async def register_node(self, **_kwargs) -> RegisteredNode:
        return RegisteredNode(
            node_id="node-1",
            credential="credential",
            dpop_nonce="node-nonce",
            credential_generation=1,
        )

    async def revoke_oauth_refresh_token(self, refresh_token: str) -> None:
        assert refresh_token == "refresh-token"


async def test_enrollment_exposes_only_redacted_state(
    tmp_path,
    monkeypatch,
) -> None:
    from qwenpaw.security import secret_store

    monkeypatch.setattr(secret_store, "_cached_master_key", b"k" * 32)
    monkeypatch.setattr(secret_store, "_cached_fernet", None)
    service = RelayEnrollmentService(
        RelayNodeStore(tmp_path / "relay.json"),
        client_factory=_FakeClient,
    )

    pending = await service.start(
        platform_url="https://platform.test",
        name="Office Paw",
        callback_port=8088,
    )
    authorization_url = urlsplit(pending.authorization_url or "")
    query = parse_qs(authorization_url.query)
    callback_url = urlsplit(query["redirect_uri"][0])
    connected = await service.complete_oauth(
        nonce=callback_url.path.rsplit("/", 1)[-1],
        state_value=query["state"][0],
        code="authorization-code",
    )

    assert pending.status == "authorization_pending"
    assert authorization_url.path == "/cli/login"
    assert query["code_challenge_method"] == ["S256"]
    assert connected.status == "connected"
    assert connected.node_id == "node-1"
    assert not hasattr(connected, "credential")

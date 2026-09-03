# -*- coding: utf-8 -*-
"""Tests for local Platform Relay enrollment orchestration."""
from __future__ import annotations

from qwenpaw.remote_access import (
    DeviceAuthorization,
    EnrollmentToken,
    RegisteredNode,
    RelayEnrollmentService,
    RelayNodeStore,
)


class _FakeClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def start_authorization(self, **_kwargs) -> DeviceAuthorization:
        return DeviceAuthorization(
            device_code="device-code",
            user_code="ABCD-EFGH",
            verification_uri="https://platform.test/device",
            expires_in=600,
            interval=5,
            dpop_nonce="device-nonce",
        )

    async def poll_authorization(
        self,
        _authorization,
        _key_pair,
    ) -> EnrollmentToken:
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
    )
    connected = await service.complete()

    assert pending.status == "authorization_pending"
    assert pending.user_code == "ABCD-EFGH"
    assert connected.status == "connected"
    assert connected.node_id == "node-1"
    assert not hasattr(connected, "credential")

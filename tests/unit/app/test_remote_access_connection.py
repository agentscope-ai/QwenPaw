# -*- coding: utf-8 -*-
"""Tests for Node Relay connection orchestration."""
from __future__ import annotations

from dataclasses import replace

import pytest

from qwenpaw.remote_access import (
    RegisteredNode,
    RelayConnectTicket,
    RelayNodeConnectionService,
    RelayNodeStore,
    RelayPairingTicket,
)


@pytest.mark.asyncio
async def test_rotated_nonce_is_saved_before_wss_connect(
    tmp_path,
    monkeypatch,
) -> None:
    from qwenpaw.remote_access import connection
    from qwenpaw.security import secret_store

    monkeypatch.setattr(secret_store, "_cached_master_key", b"k" * 32)
    monkeypatch.setattr(secret_store, "_cached_fernet", None)
    store = RelayNodeStore(tmp_path / "relay-node.json")
    state = store.create(
        platform_url="https://platform.test",
        qwenpaw_id="paw-1",
        name="Office Paw",
    )
    store.save(
        replace(
            state,
            registered_node=RegisteredNode(
                node_id="node-1",
                credential="qprn_v1.node.secret",
                dpop_nonce="old-nonce",
                credential_generation=1,
            ),
        ),
    )

    class FakeClient:
        def __init__(self, _base_url: str) -> None:
            pass

        async def create_node_connect_ticket(self, registered, _key_pair):
            assert registered.dpop_nonce == "old-nonce"
            return RelayConnectTicket(
                token="connect-ticket",
                websocket_url="wss://relay.platform.test/relay/v1/node",
                expires_in=30,
                dpop_nonce="connect-nonce",
                next_credential_dpop_nonce="new-nonce",
            )

    class FailingTransport:
        async def run(self, **_kwargs) -> None:
            loaded = store.load()
            assert loaded is not None
            assert loaded.registered_node is not None
            assert loaded.registered_node.dpop_nonce == "new-nonce"
            raise ConnectionError("offline")

    monkeypatch.setattr(connection, "PlatformRelayClient", FakeClient)
    service = RelayNodeConnectionService(store, FailingTransport())

    with pytest.raises(ConnectionError):
        await service.connect_once()


@pytest.mark.asyncio
async def test_pairing_ticket_rotates_nonce_and_checks_identity(
    tmp_path,
    monkeypatch,
) -> None:
    from qwenpaw.remote_access import connection
    from qwenpaw.security import secret_store

    monkeypatch.setattr(secret_store, "_cached_master_key", b"k" * 32)
    monkeypatch.setattr(secret_store, "_cached_fernet", None)
    store = RelayNodeStore(tmp_path / "relay-node.json")
    state = store.create(
        platform_url="https://platform.test",
        qwenpaw_id="paw-1",
        name="Office Paw",
    )
    registered = RegisteredNode(
        node_id="node-1",
        credential="qprn_v1.node.secret",
        dpop_nonce="old-nonce",
        credential_generation=1,
    )
    store.save(replace(state, registered_node=registered))

    class FakeClient:
        def __init__(self, _base_url: str) -> None:
            pass

        async def create_node_pairing_ticket(self, node, key_pair):
            assert node.dpop_nonce == "old-nonce"
            return RelayPairingTicket(
                token="pairing-ticket",
                node_id="node-1",
                qwenpaw_id="paw-1",
                node_public_key_thumbprint=key_pair.thumbprint(),
                expires_in=120,
                dpop_nonce="pairing-nonce",
                next_credential_dpop_nonce="new-nonce",
            )

    monkeypatch.setattr(connection, "PlatformRelayClient", FakeClient)
    service = RelayNodeConnectionService(store, object())
    ticket = await service.create_pairing_ticket()

    loaded = store.load()
    assert ticket.token == "pairing-ticket"
    assert loaded is not None
    assert loaded.registered_node is not None
    assert loaded.registered_node.dpop_nonce == "new-nonce"

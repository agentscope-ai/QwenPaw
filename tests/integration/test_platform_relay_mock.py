# -*- coding: utf-8 -*-
"""Integration coverage for the local Platform Relay mock."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from qwenpaw.remote_access.identity import RelayKeyPair
from qwenpaw.remote_access.protocol import (
    RelayFrame,
    RelayFrameType,
    decode_frame,
    encode_frame,
)
from tests.integration.mock_platform_relay import (
    MockConnectionContext,
    MockPlatformRelay,
    MockSessionEventStore,
    MockTicketAuthority,
)


def _context(
    role: Literal["node", "mobile"],
) -> MockConnectionContext:
    return MockConnectionContext(
        role=role,
        user_id="user-1",
        node_id="node-1",
        device_id="device-1" if role == "mobile" else None,
        credential_generation=1,
    )


def _authenticated_connection(
    relay: MockPlatformRelay,
    port: int,
    role: Literal["node", "mobile"],
    key_pair: RelayKeyPair,
):
    path = f"/relay/v1/{role}"
    target = f"ws://127.0.0.1:{port}{path}"
    token, nonce = relay.ticket_authority.issue(
        _context(role),
        key_pair.thumbprint(),
    )
    proof = key_pair.create_proof("GET", target, token, nonce)
    return connect(
        target,
        additional_headers={
            "Authorization": f"RelayTicket {token}",
            "DPoP": proof,
        },
    )


def _session_event(sequence: int, payload: bytes) -> RelayFrame:
    return RelayFrame(
        RelayFrameType.SESSION_EVENT,
        sequence=sequence,
        metadata={
            "session_id": "session-1",
            "session_revision": 1,
            "event_id": f"event-{sequence}",
            "event_type": "message.assistant.delta",
        },
        payload=payload,
    )


async def _wait_until_registered(socket: ClientConnection) -> None:
    await socket.send(encode_frame(RelayFrame(RelayFrameType.PING)))
    response = decode_frame(await socket.recv())
    assert response.frame_type is RelayFrameType.PONG


@pytest.mark.asyncio
async def test_event_is_persisted_before_ack_and_forwarded(
    tmp_path: Path,
) -> None:
    store = MockSessionEventStore(tmp_path / "relay.sqlite3")
    relay = MockPlatformRelay(store, MockTicketAuthority())
    try:
        async with serve(
            relay.handler,
            "127.0.0.1",
            0,
            compression=None,
            process_request=relay.authenticate,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            async with (
                _authenticated_connection(
                    relay,
                    port,
                    "node",
                    RelayKeyPair.generate(),
                ) as node,
                _authenticated_connection(
                    relay,
                    port,
                    "mobile",
                    RelayKeyPair.generate(),
                ) as mobile,
            ):
                await _wait_until_registered(node)
                await _wait_until_registered(mobile)
                event = _session_event(1, "你好".encode())
                await node.send(encode_frame(event))

                ack = decode_frame(await node.recv())
                forwarded = decode_frame(await mobile.recv())

                assert ack.frame_type is RelayFrameType.EVENT_ACK
                assert ack.sequence == 1
                assert forwarded == event
                persisted = await store.after(
                    _context("mobile"),
                    "session-1",
                    0,
                )
                assert [decode_frame(item) for item in persisted] == [event]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_mobile_can_resume_from_durable_sequence(
    tmp_path: Path,
) -> None:
    store = MockSessionEventStore(tmp_path / "relay.sqlite3")
    relay = MockPlatformRelay(store, MockTicketAuthority())
    events = [_session_event(1, b"one"), _session_event(2, b"two")]
    for event in events:
        await store.append(_context("node"), event)
    try:
        async with serve(
            relay.handler,
            "127.0.0.1",
            0,
            compression=None,
            process_request=relay.authenticate,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            async with _authenticated_connection(
                relay,
                port,
                "mobile",
                RelayKeyPair.generate(),
            ) as mobile:
                await mobile.send(
                    encode_frame(
                        RelayFrame(
                            RelayFrameType.RESUME,
                            sequence=1,
                            metadata={"session_id": "session-1"},
                        ),
                    ),
                )

                resumed = decode_frame(await mobile.recv())
                assert resumed == events[1]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_identical_retry_is_idempotent(tmp_path: Path) -> None:
    store = MockSessionEventStore(tmp_path / "relay.sqlite3")
    event = _session_event(1, b"same")
    context = _context("node")
    try:
        await store.append(context, event)
        await store.append(context, event)

        persisted = await store.after(context, "session-1", 0)
        assert len(persisted) == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_changed_retry_is_rejected(tmp_path: Path) -> None:
    store = MockSessionEventStore(tmp_path / "relay.sqlite3")
    context = _context("node")
    try:
        await store.append(context, _session_event(1, b"first"))
        with pytest.raises(ValueError, match="payload changed"):
            await store.append(context, _session_event(1, b"changed"))
    finally:
        store.close()


@pytest.mark.asyncio
async def test_wss_upgrade_requires_ticket_and_proof(tmp_path: Path) -> None:
    store = MockSessionEventStore(tmp_path / "relay.sqlite3")
    relay = MockPlatformRelay(store, MockTicketAuthority())
    try:
        async with serve(
            relay.handler,
            "127.0.0.1",
            0,
            compression=None,
            process_request=relay.authenticate,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            with pytest.raises(InvalidStatus):
                async with connect(
                    f"ws://127.0.0.1:{port}/relay/v1/node",
                ):
                    pass
    finally:
        store.close()


@pytest.mark.asyncio
async def test_connect_ticket_is_consumed_once(tmp_path: Path) -> None:
    store = MockSessionEventStore(tmp_path / "relay.sqlite3")
    relay = MockPlatformRelay(store, MockTicketAuthority())
    key_pair = RelayKeyPair.generate()
    try:
        async with serve(
            relay.handler,
            "127.0.0.1",
            0,
            compression=None,
            process_request=relay.authenticate,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            path = "/relay/v1/node"
            target = f"ws://127.0.0.1:{port}{path}"
            token, nonce = relay.ticket_authority.issue(
                _context("node"),
                key_pair.thumbprint(),
            )
            headers = {
                "Authorization": f"RelayTicket {token}",
                "DPoP": key_pair.create_proof(
                    "GET",
                    target,
                    token,
                    nonce,
                ),
            }
            async with connect(target, additional_headers=headers):
                pass
            with pytest.raises(InvalidStatus):
                async with connect(target, additional_headers=headers):
                    pass
    finally:
        store.close()

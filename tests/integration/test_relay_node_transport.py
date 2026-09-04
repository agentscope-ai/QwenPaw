# -*- coding: utf-8 -*-
"""End-to-end fixed-operation request through the local Relay mock."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from qwenpaw.remote_access import (
    RelayFrame,
    RelayFrameType,
    RelayKeyPair,
    RelayNodeTransport,
    RelayOperation,
    RelayOperationDispatcher,
    decode_frame,
    encode_frame,
)
from tests.integration.mock_platform_relay import (
    MockConnectionContext,
    MockPlatformRelay,
    MockSessionEventStore,
    MockTicketAuthority,
)


async def test_mobile_operation_runs_only_registered_node_handler(
    tmp_path: Path,
) -> None:
    store = MockSessionEventStore(tmp_path / "relay.sqlite3")
    relay = MockPlatformRelay(store, MockTicketAuthority())
    node_key = RelayKeyPair.generate()
    mobile_key = RelayKeyPair.generate()

    async def list_agents(payload: bytes) -> bytes:
        assert payload == b'{"enabled":true}'
        return b'{"agents":[{"id":"default"}]}'

    dispatcher = RelayOperationDispatcher(
        {RelayOperation.AGENT_LIST: list_agents},
    )
    transport = RelayNodeTransport(dispatcher)
    try:
        async with serve(
            relay.handler,
            "127.0.0.1",
            0,
            compression=None,
            process_request=relay.authenticate,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            node_url = f"ws://127.0.0.1:{port}/relay/v1/node"
            mobile_url = f"ws://127.0.0.1:{port}/relay/v1/mobile"
            node_ticket, node_nonce = relay.ticket_authority.issue(
                _context("node"),
                node_key.thumbprint(),
            )
            mobile_ticket, mobile_nonce = relay.ticket_authority.issue(
                _context("mobile"),
                mobile_key.thumbprint(),
            )
            node_task = asyncio.create_task(
                transport.run(
                    websocket_url=node_url,
                    ticket=node_ticket,
                    dpop_nonce=node_nonce,
                    key_pair=node_key,
                ),
            )
            async with connect(
                mobile_url,
                additional_headers={
                    "Authorization": f"RelayTicket {mobile_ticket}",
                    "DPoP": mobile_key.create_proof(
                        "GET",
                        mobile_url,
                        mobile_ticket,
                        mobile_nonce,
                    ),
                },
            ) as mobile:
                await asyncio.sleep(0)
                await mobile.send(
                    encode_frame(
                        RelayFrame(
                            RelayFrameType.OPEN,
                            stream_id="stream-1",
                            request_id="request-1",
                            metadata={
                                "operation_id": "agent.list",
                                "schema_version": 1,
                            },
                        ),
                    ),
                )
                await mobile.send(
                    encode_frame(
                        RelayFrame(
                            RelayFrameType.DATA,
                            stream_id="stream-1",
                            payload=b'{"enabled":true}',
                        ),
                    ),
                )
                await mobile.send(
                    encode_frame(
                        RelayFrame(
                            RelayFrameType.END,
                            stream_id="stream-1",
                        ),
                    ),
                )

                meta = decode_frame(await mobile.recv())
                data = decode_frame(await mobile.recv())
                end = decode_frame(await mobile.recv())

                assert meta.frame_type is RelayFrameType.RESULT_META
                assert data.payload == b'{"agents":[{"id":"default"}]}'
                assert end.frame_type is RelayFrameType.END
            node_task.cancel()
            await asyncio.gather(node_task, return_exceptions=True)
    finally:
        store.close()


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

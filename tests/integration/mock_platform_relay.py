# -*- coding: utf-8 -*-
"""Local-only Platform Relay mock used by integration tests and demos."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
import time
from typing import Literal
from urllib.parse import urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request, Response

from qwenpaw.remote_access.identity import RelayProofError, verify_proof
from qwenpaw.remote_access.protocol import (
    RelayFrame,
    RelayFrameType,
    decode_frame,
    encode_frame,
)


@dataclass(frozen=True, slots=True)
class MockConnectionContext:
    """Identity established before a mock WebSocket is upgraded."""

    role: Literal["node", "mobile"]
    user_id: str
    node_id: str
    device_id: str | None
    credential_generation: int


@dataclass(frozen=True, slots=True)
class MockConnectTicket:
    """A hashed, short-lived and proof-bound mock connection ticket."""

    token_hash: str
    nonce: str
    public_key_thumbprint: str
    context: MockConnectionContext
    expires_at: int


class MockTicketAuthority:
    """Issue and atomically consume local-only Relay connect tickets."""

    def __init__(self) -> None:
        self._tickets: dict[str, MockConnectTicket] = {}
        self._lock = asyncio.Lock()

    def issue(
        self,
        context: MockConnectionContext,
        public_key_thumbprint: str,
        *,
        now: int | None = None,
        ttl_seconds: int = 30,
    ) -> tuple[str, str]:
        """Return a raw test ticket and nonce while storing only its hash."""
        if ttl_seconds <= 0 or ttl_seconds > 30:
            raise ValueError("Connect ticket TTL must be between 1 and 30")
        token = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(24)
        token_hash = _token_hash(token)
        issued_at = int(time.time()) if now is None else now
        self._tickets[token_hash] = MockConnectTicket(
            token_hash=token_hash,
            nonce=nonce,
            public_key_thumbprint=public_key_thumbprint,
            context=context,
            expires_at=issued_at + ttl_seconds,
        )
        return token, nonce

    async def consume(
        self,
        authorization: str | None,
        proof: str | None,
        target: str,
        expected_role: Literal["node", "mobile"],
        *,
        now: int | None = None,
    ) -> MockConnectionContext:
        """Validate proof and consume one ticket exactly once."""
        prefix = "RelayTicket "
        if not authorization or not authorization.startswith(prefix):
            raise RelayProofError("Relay ticket authorization is missing")
        if not proof:
            raise RelayProofError("Relay proof is missing")
        token = authorization[len(prefix) :]
        if not token:
            raise RelayProofError("Relay ticket is missing")
        token_hash = _token_hash(token)
        current_time = int(time.time()) if now is None else now
        async with self._lock:
            ticket = self._tickets.get(token_hash)
            if ticket is None:
                raise RelayProofError("Relay ticket is invalid")
            if ticket.expires_at < current_time:
                self._tickets.pop(token_hash, None)
                raise RelayProofError("Relay ticket is expired")
            if ticket.context.role != expected_role:
                raise RelayProofError("Relay ticket role is invalid")
            verify_proof(
                proof,
                "GET",
                target,
                token,
                ticket.nonce,
                expected_thumbprint=ticket.public_key_thumbprint,
                now=current_time,
            )
            self._tickets.pop(token_hash, None)
            return ticket.context


class MockSessionEventStore:
    """Small durable event store with the production idempotency contract."""

    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS secure_relay_session_events (
                user_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                session_revision INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                frame BLOB NOT NULL,
                PRIMARY KEY (user_id, node_id, session_id, event_id),
                UNIQUE (user_id, node_id, session_id, sequence)
            )
            """,
        )
        self._connection.commit()

    async def append(
        self,
        context: MockConnectionContext,
        frame: RelayFrame,
    ) -> None:
        """Persist one event, treating an identical retry as success."""
        metadata = frame.metadata
        session_id = str(metadata["session_id"])
        event_id = str(metadata["event_id"])
        session_revision = int(metadata["session_revision"])
        assert frame.sequence is not None
        wire = encode_frame(frame)
        async with self._lock:
            existing = self._connection.execute(
                """
                SELECT event_id, session_revision, frame
                FROM secure_relay_session_events
                WHERE user_id = ? AND node_id = ?
                  AND session_id = ? AND sequence = ?
                """,
                (
                    context.user_id,
                    context.node_id,
                    session_id,
                    frame.sequence,
                ),
            ).fetchone()
            if existing is not None:
                if existing["event_id"] != event_id:
                    raise ValueError("Session sequence already has an event")
                if bytes(existing["frame"]) != wire:
                    raise ValueError("Retried Session event payload changed")
                return
            latest = self._connection.execute(
                """
                SELECT MAX(session_revision) AS session_revision
                FROM secure_relay_session_events
                WHERE user_id = ? AND node_id = ? AND session_id = ?
                """,
                (context.user_id, context.node_id, session_id),
            ).fetchone()
            current_revision = latest["session_revision"]
            if (
                current_revision is not None
                and session_revision < current_revision
            ):
                raise ValueError("Session revision is stale")
            self._connection.execute(
                """
                INSERT INTO secure_relay_session_events (
                    user_id, node_id, session_id, session_revision,
                    event_id, sequence, frame
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context.user_id,
                    context.node_id,
                    session_id,
                    session_revision,
                    event_id,
                    frame.sequence,
                    wire,
                ),
            )
            self._connection.commit()

    async def after(
        self,
        context: MockConnectionContext,
        session_id: str,
        sequence: int,
    ) -> list[bytes]:
        """Return encoded events after the supplied durable cursor."""
        async with self._lock:
            rows = self._connection.execute(
                """
                SELECT frame
                FROM secure_relay_session_events
                WHERE user_id = ? AND node_id = ?
                  AND session_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (
                    context.user_id,
                    context.node_id,
                    session_id,
                    sequence,
                ),
            ).fetchall()
        return [bytes(row["frame"]) for row in rows]

    def close(self) -> None:
        """Close the SQLite connection."""
        self._connection.close()


class MockPlatformRelay:
    """Route Node and Mobile frames while persisting Session events."""

    def __init__(
        self,
        event_store: MockSessionEventStore,
        ticket_authority: MockTicketAuthority,
    ) -> None:
        self._event_store = event_store
        self.ticket_authority = ticket_authority
        self._nodes: dict[str, ServerConnection] = {}
        self._mobiles: dict[str, set[ServerConnection]] = defaultdict(set)
        self._contexts: dict[ServerConnection, MockConnectionContext] = {}
        self._lock = asyncio.Lock()

    async def authenticate(
        self,
        socket: ServerConnection,
        request: Request,
    ) -> Response | None:
        """Authenticate a peer before the WebSocket upgrade completes."""
        parsed = urlsplit(request.path)
        roles: dict[str, Literal["node", "mobile"]] = {
            "/relay/v1/node": "node",
            "/relay/v1/mobile": "mobile",
        }
        role = roles.get(parsed.path)
        if role is None or parsed.query or request.headers.get("Origin"):
            return socket.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")
        host = request.headers.get("Host")
        if not host:
            return socket.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        target = f"ws://{host}{parsed.path}"
        try:
            context = await self.ticket_authority.consume(
                request.headers.get("Authorization"),
                request.headers.get("DPoP"),
                target,
                role,
            )
        except RelayProofError:
            return socket.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        self._contexts[socket] = context
        return None

    async def handler(self, socket: ServerConnection) -> None:
        """Route frames using the identity fixed during WSS Upgrade."""
        context = self._contexts.get(socket)
        if context is None:
            await socket.close(code=4003, reason="Unauthenticated")
            return
        try:
            await self._register(socket, context)
            async for raw in socket:
                if not isinstance(raw, bytes):
                    await self._send_error(socket, "BINARY_REQUIRED")
                    continue
                await self._route(socket, context, decode_frame(raw))
        finally:
            await self._unregister(socket, context)
            self._contexts.pop(socket, None)

    async def _register(
        self,
        socket: ServerConnection,
        context: MockConnectionContext,
    ) -> None:
        async with self._lock:
            if context.role == "node":
                previous = self._nodes.get(context.node_id)
                self._nodes[context.node_id] = socket
                if previous is not None and previous is not socket:
                    await previous.close(code=4001, reason="Node replaced")
            else:
                self._mobiles[context.node_id].add(socket)

    async def _unregister(
        self,
        socket: ServerConnection,
        context: MockConnectionContext,
    ) -> None:
        async with self._lock:
            node_id = context.node_id
            if context.role == "node" and self._nodes.get(node_id) is socket:
                self._nodes.pop(node_id, None)
            if context.role == "mobile":
                self._mobiles[node_id].discard(socket)
                if not self._mobiles[node_id]:
                    self._mobiles.pop(node_id, None)

    async def _route(
        self,
        socket: ServerConnection,
        context: MockConnectionContext,
        frame: RelayFrame,
    ) -> None:
        if frame.frame_type is RelayFrameType.PING:
            await socket.send(
                encode_frame(RelayFrame(RelayFrameType.PONG)),
            )
            return
        if context.role == "node":
            if frame.frame_type is RelayFrameType.SESSION_EVENT:
                await self._event_store.append(context, frame)
                await socket.send(encode_frame(self._ack(frame)))
            await self._broadcast_mobile(context.node_id, encode_frame(frame))
            return
        if frame.frame_type is RelayFrameType.RESUME:
            await self._resume(socket, context, frame)
            return
        node = self._nodes.get(context.node_id)
        if node is None:
            await self._send_error(socket, "NODE_OFFLINE")
            return
        await node.send(encode_frame(frame))

    async def _resume(
        self,
        socket: ServerConnection,
        context: MockConnectionContext,
        frame: RelayFrame,
    ) -> None:
        session_id = str(frame.metadata.get("session_id", ""))
        if not session_id or frame.sequence is None:
            await self._send_error(socket, "INVALID_RESUME")
            return
        for wire in await self._event_store.after(
            context,
            session_id,
            frame.sequence,
        ):
            await socket.send(wire)

    async def _broadcast_mobile(self, node_id: str, wire: bytes) -> None:
        sockets = tuple(self._mobiles.get(node_id, ()))
        for socket in sockets:
            await socket.send(wire)

    @staticmethod
    def _ack(frame: RelayFrame) -> RelayFrame:
        return RelayFrame(
            RelayFrameType.EVENT_ACK,
            sequence=frame.sequence,
            metadata={"session_id": frame.metadata["session_id"]},
        )

    @staticmethod
    async def _send_error(
        socket: ServerConnection,
        code: str,
    ) -> None:
        await socket.send(
            encode_frame(
                RelayFrame(
                    RelayFrameType.ERROR,
                    stream_id="connection",
                    metadata={"code": code},
                ),
            ),
        )


async def run_mock(host: str, port: int, database: Path) -> None:
    """Run the local mock until interrupted."""
    store = MockSessionEventStore(database)
    relay = MockPlatformRelay(store, MockTicketAuthority())
    try:
        async with serve(
            relay.handler,
            host,
            port,
            compression=None,
            process_request=relay.authenticate,
        ):
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "url": f"ws://{host}:{port}",
                        "database": str(database),
                    },
                ),
                flush=True,
            )
            await asyncio.Future()
    finally:
        store.close()


def main() -> None:
    """Parse local development arguments and start the Relay mock."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument(
        "--database",
        default=Path(".codex-tmp/qwenpaw-relay-mock.sqlite3"),
        type=Path,
    )
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run_mock(args.host, args.port, args.database))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    main()

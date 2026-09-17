# -*- coding: utf-8 -*-
"""Bidirectional WebSocket relay for QwenPaw Hub runtimes."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed


def _public_close_code(code: int | None) -> int:
    if code is not None and (1000 <= code <= 1014 or 3000 <= code <= 4999):
        return code
    return 1011


async def _client_to_upstream(
    client: WebSocket,
    upstream: ClientConnection,
) -> None:
    try:
        while True:
            message = await client.receive()
            if message["type"] == "websocket.disconnect":
                await upstream.close(
                    code=_public_close_code(message.get("code")),
                )
                return
            text = message.get("text")
            if text is not None:
                await upstream.send(text)
                continue
            data = message.get("bytes")
            if data is not None:
                await upstream.send(data)
    except WebSocketDisconnect as exc:
        await upstream.close(code=_public_close_code(exc.code))


async def _upstream_to_client(
    client: WebSocket,
    upstream: ClientConnection,
) -> None:
    try:
        async for message in upstream:
            if isinstance(message, str):
                await client.send_text(message)
            else:
                await client.send_bytes(message)
    except ConnectionClosed as exc:
        close = exc.rcvd or exc.sent
        with suppress(RuntimeError):
            await client.close(
                code=_public_close_code(close.code if close else None),
                reason=close.reason if close else "",
            )
    else:
        with suppress(RuntimeError):
            await client.close(
                code=_public_close_code(upstream.close_code),
                reason=upstream.close_reason or "",
            )


async def relay_websocket(
    client: WebSocket,
    upstream_url: str,
    *,
    headers: Mapping[str, str],
    max_size: int,
) -> None:
    """Relay text, binary, and close frames until either peer disconnects."""
    requested_protocols = [
        value.strip()
        for value in client.headers.get("sec-websocket-protocol", "").split(
            ",",
        )
        if value.strip()
    ]
    async with connect(
        upstream_url,
        additional_headers=dict(headers),
        subprotocols=requested_protocols or None,
        proxy=None,
        max_size=max_size,
    ) as upstream:
        await client.accept(subprotocol=upstream.subprotocol)
        tasks = {
            asyncio.create_task(_client_to_upstream(client, upstream)),
            asyncio.create_task(_upstream_to_client(client, upstream)),
        }
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

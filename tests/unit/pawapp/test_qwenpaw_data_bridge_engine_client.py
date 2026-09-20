# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Focused tests for normalized bridge HTTP and SSE behavior."""
from __future__ import annotations

from typing import Any

import httpx
import pytest


def _client(bridge_engine_client, handler: Any):
    client = bridge_engine_client.EngineClient(
        lambda: ("http://engine.test", "token"),
    )
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    )
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [404, 500])
async def test_http_errors_are_normalized_without_response_body(
    bridge_engine_client,
    status_code: int,
) -> None:
    secret = "secret-token-from-engine-body"
    client = _client(
        bridge_engine_client,
        lambda _request: httpx.Response(status_code, text=secret),
    )

    try:
        with pytest.raises(
            bridge_engine_client.EngineResponseError,
        ) as excinfo:
            await client.list_datasources()
    finally:
        await client.aclose()

    assert excinfo.value.status_code == status_code
    assert len(excinfo.value.detail) <= 160
    assert secret not in excinfo.value.detail
    assert secret not in str(excinfo.value)


@pytest.mark.asyncio
async def test_sse_setup_error_is_normalized(bridge_engine_client) -> None:
    client = _client(
        bridge_engine_client,
        lambda _request: httpx.Response(404, text="private session detail"),
    )

    try:
        with pytest.raises(
            bridge_engine_client.EngineResponseError,
        ) as excinfo:
            async for _frame in client.stream_events("ses", "chat"):
                pass
    finally:
        await client.aclose()

    assert excinfo.value.status_code == 404
    assert "private session detail" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_sse_flushes_final_frame_without_blank_separator(
    bridge_engine_client,
) -> None:
    payload = b'data: {"object":"response","status":"completed"}\n'
    client = _client(
        bridge_engine_client,
        lambda _request: httpx.Response(
            200,
            content=payload,
            headers={"content-type": "text/event-stream"},
        ),
    )

    try:
        frames = [frame async for frame in client.stream_events("ses", "chat")]
    finally:
        await client.aclose()

    assert frames == [{"object": "response", "status": "completed"}]

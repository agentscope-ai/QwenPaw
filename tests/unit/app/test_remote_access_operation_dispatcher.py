# -*- coding: utf-8 -*-
"""Tests for the Relay fixed-operation local API adapter."""
from __future__ import annotations

import json

import httpx
import pytest

from qwenpaw.remote_access import RelayLocalApi, RelayOperation


@pytest.mark.asyncio
async def test_session_list_maps_to_one_fixed_loopback_route() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = (
            await RelayLocalApi(client=client)
            .dispatcher()
            .dispatch(
                RelayOperation.SESSION_LIST,
                b'{"agent_id":"default","archived":true}',
            )
        )

    assert result == b"[]"
    assert requests[0].url == "http://127.0.0.1:8088/api/chats?archived=true"
    assert requests[0].headers["X-Agent-Id"] == "default"


@pytest.mark.asyncio
async def test_identifiers_cannot_turn_relay_into_a_path_proxy() -> None:
    dispatcher = RelayLocalApi().dispatcher()

    with pytest.raises(ValueError):
        await dispatcher.dispatch(
            RelayOperation.SESSION_GET,
            b'{"chat_id":"../../workspace"}',
        )


@pytest.mark.asyncio
async def test_chat_update_keeps_destination_group_in_business_body() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "chat-1"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        await RelayLocalApi(client=client).dispatcher().dispatch(
            RelayOperation.SESSION_UPDATE,
            b'{"chat_id":"chat-1","group_id":"group-2"}',
        )

    assert requests[0].url.path == "/api/chats/chat-1"
    assert json.loads(requests[0].content) == {"group_id": "group-2"}

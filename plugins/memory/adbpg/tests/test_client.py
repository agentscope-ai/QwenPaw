# -*- coding: utf-8 -*-
"""ADBPG REST contract and failure handling tests without external services."""

# pylint: disable=protected-access

import asyncio
import json

import httpx
import pytest

from plugins.memory.adbpg.backend.client import ADBPGConfig, ADBPGMemoryClient


async def _client(handler) -> ADBPGMemoryClient:
    client = ADBPGMemoryClient(
        ADBPGConfig(
            rest_base_url="https://memory.example.test/",
            rest_api_key="test-key",
        ),
    )
    await client._http_client.aclose()
    client._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    )
    return client


@pytest.mark.asyncio
async def test_add_and_search_keep_identity_and_metadata_contract():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    client = await _client(handler)
    try:
        await client.add_memory(
            messages=[{"role": "user", "content": "I like cats"}],
            user_id="user-a",
            agent_id="agent-a",
            run_id="run-a",
            metadata={"source": "test"},
        )
        await client.search_memory(
            query="Which animal do I like?",
            user_id="user-a",
            agent_id="agent-a",
            run_id="another-run",
            limit=2,
        )
    finally:
        await client.close()

    add, search = requests
    assert add.url.path == "/v3/memories/add/"
    assert add.headers["Authorization"] == "Token test-key"
    assert json.loads(add.content) == {
        "messages": [{"role": "user", "content": "I like cats"}],
        "user_id": "user-a",
        "agent_id": "agent-a",
        "run_id": "run-a",
        "metadata": {"source": "test"},
    }
    assert search.url.path == "/v3/memories/search/"
    assert json.loads(search.content) == {
        "query": "Which animal do I like?",
        "filters": {"user_id": "user-a", "agent_id": "agent-a"},
        "top_k": 2,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 503])
async def test_add_propagates_http_failure(status):
    client = await _client(
        lambda request: httpx.Response(status, json={"detail": "rejected"}),
    )
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await client.add_memory(
                [{"role": "user", "content": "remember me"}],
                user_id="user-a",
            )
        assert exc.value.response.status_code == status
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_add_propagates_transport_failure():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    client = await _client(handler)
    try:
        with pytest.raises(httpx.ConnectError, match="offline"):
            await client.add_memory(
                [{"role": "user", "content": "remember me"}],
                user_id="user-a",
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_add_does_not_swallow_cancellation():
    async def handler(request):
        raise asyncio.CancelledError()

    client = await _client(handler)
    try:
        with pytest.raises(asyncio.CancelledError):
            await client.add_memory(
                [{"role": "user", "content": "remember me"}],
                user_id="user-a",
            )
    finally:
        await client.close()

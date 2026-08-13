from unittest.mock import AsyncMock

import httpx
import pytest

from qwenpaw.agents.memory.powercontext_client import PowerContextConfig, PowerContextMemoryClient


@pytest.mark.asyncio
async def test_client_maps_remember_and_search_requests():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"hits": [{"text": "decision", "score": 0.9}]}
            if request.url.path.endswith("/search")
            else {"memory": {"id": "m1"}},
        ),
    )
    client = PowerContextMemoryClient(PowerContextConfig("http://pc", token="tok", scope_id="project:x"))
    await client._http.aclose()
    client._http = httpx.AsyncClient(transport=transport, base_url="http://pc", headers={"Authorization": "Bearer tok"})
    await client.remember(kind="decision", text="use A")
    hits = await client.search(query="choice", limit=2)
    assert hits[0]["text"] == "decision"
    await client.close()


@pytest.mark.asyncio
async def test_client_propagates_http_errors():
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "down"}))
    client = PowerContextMemoryClient(PowerContextConfig("http://pc"))
    await client._http.aclose()
    client._http = httpx.AsyncClient(transport=transport, base_url="http://pc")
    with pytest.raises(httpx.HTTPStatusError):
        await client.search(query="x")
    await client.close()

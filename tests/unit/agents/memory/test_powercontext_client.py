from unittest.mock import AsyncMock

import httpx
import pytest

from qwenpaw.agents.memory.powercontext_client import (
    PowerContextConfig,
    PowerContextHTTPError,
    PowerContextMemoryClient,
)


@pytest.mark.asyncio
async def test_client_maps_remember_and_search_requests():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=(
                {"hits": [{"text": "decision", "score": 0.9}]}
                if request.url.path.endswith("/search")
                else {"memory": {"id": "m1"}}
            ),
        ),
    )
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", token="tok", scope_id="project:x")
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=transport,
        base_url="http://pc",
        headers={"Authorization": "Bearer tok"},
    )
    await client.remember(kind="decision", text="use A")
    hits = await client.search(query="choice", limit=2)
    assert hits[0]["text"] == "decision"
    await client.close()

@pytest.mark.asyncio
async def test_client_reports_safe_http_error_summary_without_headers():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"error": "down"})
    )
    client = PowerContextMemoryClient(PowerContextConfig("http://pc"))
    await client._http.aclose()
    client._http = httpx.AsyncClient(transport=transport, base_url="http://pc")
    with pytest.raises(PowerContextHTTPError) as error:
        await client.search(query="x")
    assert error.value.status_code == 503
    assert "down" in str(error.value)
    assert "Bearer" not in str(error.value)
    await client.close()


@pytest.mark.asyncio
async def test_client_redacts_token_if_server_echoes_it():
    token = "secret-token"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"message": token})
    )
    client = PowerContextMemoryClient(PowerContextConfig("http://pc", token=token))
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=transport,
        base_url="http://pc",
        headers={"Authorization": f"Bearer {token}"},
    )
    with pytest.raises(PowerContextHTTPError) as error:
        await client.search(query="x")
    assert token not in str(error.value)
    assert "<redacted>" in str(error.value)
    await client.close()

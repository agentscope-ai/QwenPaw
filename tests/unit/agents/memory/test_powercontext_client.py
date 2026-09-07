# -*- coding: utf-8 -*-
# pylint: disable=protected-access

import json

import httpx
import pytest

from qwenpaw.agents.memory.powercontext_client import (
    MAX_MEMORY_TEXT_BYTES,
    PowerContextConfig,
    PowerContextHTTPError,
    PowerContextMemoryClient,
    PowerContextProtocolError,
    PowerContextRequestValidationError,
)


@pytest.mark.asyncio
async def test_client_maps_remember_and_search_requests():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "text": "decision",
                            "score": 0.9,
                            "matched_by": ["fts"],
                            "citation": {
                                "memory_ref": {
                                    "family": "memory",
                                    "artifact_id": "memory",
                                    "revision": 1,
                                },
                                "entry_id": "entry-1",
                                "entry_version_id": "version-1",
                            },
                        },
                    ],
                },
            )
        return httpx.Response(200, json={"memory": {"id": "m1"}})

    transport = httpx.MockTransport(
        handler,
    )
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", token="tok", scope_id="project:x"),
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
    assert requests[0].url.path == "/v1/memory/remember"
    assert requests[0].headers["Authorization"] == "Bearer tok"
    assert json.loads(requests[0].content) == {
        "scope_id": "project:x",
        "kind": "decision",
        "text": "use A",
    }
    assert requests[1].url.path == "/v1/memory/search"
    assert json.loads(requests[1].content) == {
        "scope_id": "project:x",
        "query": "choice",
        "limit": 2,
    }
    await client.close()


@pytest.mark.asyncio
async def test_client_rejects_overlimit_text_and_bounds_search_limit():
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"hits": []})

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://pc",
    )
    with pytest.raises(PowerContextRequestValidationError, match="UTF-8"):
        await client.remember(kind="fact", text="你" * 3000)
    await client.search(query="x", limit=0)
    await client.search(query="x", limit=100)
    assert payloads[0]["limit"] == 1
    assert payloads[1]["limit"] == 50
    assert MAX_MEMORY_TEXT_BYTES == 8000
    await client.close()


@pytest.mark.asyncio
async def test_client_rejects_invalid_request_fields_before_network_io():
    def fail_if_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.url}")

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(fail_if_called),
        base_url="http://pc",
    )

    with pytest.raises(PowerContextRequestValidationError, match="scope_id"):
        await client.search(query="x", scope_id="   ")
    with pytest.raises(PowerContextRequestValidationError, match="scope_id"):
        await client.search(query="x", scope_id="s" * 257)
    with pytest.raises(PowerContextRequestValidationError, match="kind"):
        await client.remember(kind="k" * 129, text="memory")
    with pytest.raises(PowerContextRequestValidationError, match="query"):
        await client.search(query="x" * 8193)

    await client.close()


@pytest.mark.asyncio
async def test_client_rejects_success_response_without_hits():
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"error": "down"}),
        ),
        base_url="http://pc",
    )
    with pytest.raises(PowerContextProtocolError, match="hits list"):
        await client.search(query="x")
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hit", "message"),
    [
        ("not-an-object", "hit 0 must be an object"),
        ({"score": 0.5}, "hit 0 has an invalid text"),
        (
            {
                "text": "memory",
                "score": 0.5,
                "citation": {},
                "matched_by": [],
                "unexpected": "server-data",
            },
            "hit 0 has an invalid fields",
        ),
        (
            {
                "text": "memory",
                "score": "not-a-number",
                "citation": {},
                "matched_by": [],
            },
            "hit 0 has an invalid score",
        ),
        (
            {
                "text": "memory",
                "score": 2.0,
                "citation": {},
                "matched_by": [],
            },
            "hit 0 has an invalid score",
        ),
        (
            {
                "text": "memory",
                "score": 0.5,
                "citation": {},
                "matched_by": [],
            },
            "hit 0 has an invalid citation",
        ),
        (
            {
                "text": "memory",
                "score": 0.5,
                "citation": {
                    "memory_ref": {
                        "family": "memory",
                        "artifact_id": "memory",
                        "revision": 1,
                    },
                    "entry_id": "entry-1",
                    "entry_version_id": "version-1",
                },
                "matched_by": ["unknown"],
            },
            "hit 0 has an invalid matched_by",
        ),
        (
            {
                "text": "memory",
                "score": 0.5,
                "citation": {
                    "memory_ref": {
                        "family": "memory with spaces",
                        "artifact_id": "memory",
                        "revision": 1,
                    },
                    "entry_id": "entry-1",
                    "entry_version_id": "version-1",
                },
                "matched_by": ["fts"],
            },
            "hit 0 has an invalid citation",
        ),
    ],
)
async def test_client_rejects_malformed_successful_search_hits(hit, message):
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"hits": [hit]}),
        ),
        base_url="http://pc",
    )

    with pytest.raises(PowerContextProtocolError, match=message):
        await client.search(query="x")

    await client.close()


@pytest.mark.asyncio
async def test_malformed_successful_hit_does_not_echo_bearer_token():
    token = "pc-secret-token-should-not-leak"
    client = PowerContextMemoryClient(
        PowerContextConfig(
            "http://pc",
            token=token,
            scope_id="agent:test",
        ),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "text": "memory",
                            "score": token,
                            "citation": {},
                            "matched_by": [],
                        },
                    ],
                },
            ),
        ),
        base_url="http://pc",
    )

    with pytest.raises(PowerContextProtocolError) as error:
        await client.search(query="x")

    assert token not in str(error.value)
    assert "hit 0 has an invalid score" in str(error.value)
    await client.close()


@pytest.mark.asyncio
async def test_client_reports_safe_http_error_summary_without_headers():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"error": "down"}),
    )
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
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
        lambda request: httpx.Response(503, json={"message": token}),
    )
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", token=token, scope_id="agent:test"),
    )
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

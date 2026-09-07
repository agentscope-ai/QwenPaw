# -*- coding: utf-8 -*-
"""Contract tests for the SDK-free OpenViking REST client."""

import json
import httpx
import pytest

from qwenpaw.agents.memory.openviking_client import (
    OpenVikingClient,
    OpenVikingClientConfig,
    OpenVikingConfigurationError,
    OpenVikingServiceError,
)


def _json_response(status: int, data: dict) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(data).encode(),
        headers={"content-type": "application/json"},
    )


@pytest.mark.asyncio
async def test_client_uses_rest_contract_and_updates_existing_policy():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return _json_response(
                200,
                {
                    "auth_mode": "api_key",
                    "account_id": "test",
                    "user_id": "qwenpaw",
                },
            )
        if request.method == "POST" and request.url.path == "/api/v1/sessions":
            return _json_response(409, {"detail": "already exists"})
        return _json_response(200, {"status": "success", "result": {}})

    client = OpenVikingClient(
        OpenVikingClientConfig("http://openviking:1933", "tenant-key", 3),
        transport=httpx.MockTransport(handler),
    )
    try:
        identity = await client.resolve_identity()
        await client.ensure_session("session-1", auto_commit_policy=None)
    finally:
        await client.close()

    assert identity.namespace == "test/qwenpaw"
    assert [request.method for request in requests] == ["GET", "POST", "PATCH"]
    assert requests[0].headers["x-api-key"] == "tenant-key"
    assert json.loads(requests[1].content)["auto_commit_policy"] is None
    assert json.loads(requests[2].content) == {"auto_commit_policy": None}


@pytest.mark.asyncio
async def test_client_sends_bounded_context_search_request():
    request_body = {}
    request_path = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_path
        request_path = request.url.path
        request_body.update(json.loads(request.content))
        return _json_response(
            200,
            {
                "status": "success",
                "result": {"rendered": "remembered fact"},
            },
        )

    client = OpenVikingClient(
        OpenVikingClientConfig("http://openviking:1933", "key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.search_context(
            query="customer preference",
            session_id="mapped-session",
            max_results=3,
            token_budget=512,
        )
    finally:
        await client.close()

    assert result == {"rendered": "remembered fact"}
    assert request_path == "/api/v1/search/search"
    assert request_body == {
        "query": "customer preference",
        "context_type": "memory",
        "session_id": "mapped-session",
        "limit": 3,
        "mode": "context",
        "query_expansion": "off",
        "max_tokens": 512,
    }


@pytest.mark.asyncio
async def test_invalid_key_is_configuration_error():
    client = OpenVikingClient(
        OpenVikingClientConfig("http://openviking:1933", "bad"),
        transport=httpx.MockTransport(
            lambda request: _json_response(
                200,
                {"auth_mode": "api_key", "version": "0.4.16"},
            ),
        ),
    )
    try:
        with pytest.raises(OpenVikingConfigurationError, match="API key"):
            await client.resolve_identity()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 503])
async def test_temporary_http_error_is_service_error(
    status_code: int,
):
    client = OpenVikingClient(
        OpenVikingClientConfig("http://openviking:1933", "key"),
        transport=httpx.MockTransport(
            lambda request: _json_response(
                status_code,
                {"detail": "temporarily unavailable"},
            ),
        ),
    )
    try:
        with pytest.raises(
            OpenVikingServiceError,
            match=f"HTTP {status_code}",
        ):
            await client.search_memories(query="x", max_results=2)
    finally:
        await client.close()

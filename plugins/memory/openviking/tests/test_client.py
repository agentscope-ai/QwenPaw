# -*- coding: utf-8 -*-
"""REST-contract and secret-safe error tests for the OpenViking client."""

import json

import httpx
import pytest

from plugins.memory.openviking.backend.client import (
    OpenVikingClient,
    OpenVikingClientConfig,
    OpenVikingConfigurationError,
    OpenVikingServiceError,
)


def _client(handler, *, api_key="test-tenant-key"):
    return OpenVikingClient(
        OpenVikingClientConfig("http://openviking.test", api_key),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_client_uses_rest_contract_and_updates_existing_policy():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "auth_mode": "api_key",
                    "account_id": "a",
                    "user_id": "u",
                },
            )
        if request.method == "POST":
            return httpx.Response(409, json={})
        return httpx.Response(200, json={"status": "ok", "result": {}})

    client = _client(handler)
    identity = await client.resolve_identity()
    await client.ensure_session("session-1", auto_commit_policy={"n": 2})
    await client.close()

    assert identity.namespace == "a/u"
    assert [(item.method, item.url.path) for item in seen] == [
        ("GET", "/health"),
        ("POST", "/api/v1/sessions"),
        ("PATCH", "/api/v1/sessions/session-1/config"),
    ]
    assert seen[1].headers["X-API-Key"] == "test-tenant-key"
    assert json.loads(seen[2].content) == {"auto_commit_policy": {"n": 2}}


@pytest.mark.asyncio
async def test_client_sends_bounded_context_search_request():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"status": "ok", "result": {"digest": "memory"}},
        )

    client = _client(handler)
    result = await client.search_context(
        query="project code",
        session_id="session-1",
        max_results=3,
        token_budget=2048,
    )
    await client.close()

    assert result == {"digest": "memory"}
    assert requests[0].url.path == "/api/v1/search/search"
    assert json.loads(requests[0].content) == {
        "query": "project code",
        "context_type": "memory",
        "session_id": "session-1",
        "limit": 3,
        "mode": "context",
        "query_expansion": "off",
        "max_tokens": 2048,
    }


@pytest.mark.asyncio
async def test_invalid_key_is_configuration_error():
    client = _client(
        lambda request: httpx.Response(
            200,
            json={"auth_mode": "api_key", "account_id": "", "user_id": ""},
        ),
    )

    with pytest.raises(OpenVikingConfigurationError, match="rejected"):
        await client.resolve_identity()
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_temporary_http_error_is_service_error(status):
    client = _client(lambda request: httpx.Response(status, text="temporary"))

    with pytest.raises(OpenVikingServiceError, match=f"HTTP {status}"):
        await client.search_memories(query="q", max_results=1)
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("json_error", [False, True])
async def test_server_response_never_echoes_tenant_key(json_error):
    key = "tenant-key-must-not-leak"
    response = (
        httpx.Response(
            200,
            json={
                "status": "error",
                "error": {"code": "INTERNAL_ERROR", "message": key},
            },
        )
        if json_error
        else httpx.Response(503, text="server saw " + key)
    )
    client = _client(
        lambda request: response,
        api_key=key,
    )

    with pytest.raises(OpenVikingServiceError) as caught:
        await client.search_memories(query="q", max_results=1)
    await client.close()

    assert key not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, payload, expected_error",
    [
        (302, {"status": "ok", "result": {}}, OpenVikingConfigurationError),
        (409, {}, OpenVikingConfigurationError),
        (200, {}, OpenVikingServiceError),
        (200, {"result": {}}, OpenVikingServiceError),
        (200, {"status": "ok"}, OpenVikingServiceError),
        (200, {"status": "ok", "result": None}, OpenVikingServiceError),
        (200, {"status": "ok", "result": []}, OpenVikingServiceError),
    ],
)
async def test_append_rejects_unconfirmed_success(
    status,
    payload,
    expected_error,
):
    client = _client(
        lambda request: httpx.Response(
            status,
            json=payload,
            headers={"Location": "http://redirect.test"},
        ),
    )
    try:
        with pytest.raises(expected_error):
            await client.add_messages(
                "session-1",
                [{"role": "user", "content": "hello"}],
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_commit_sends_archive_policy_and_preserves_task_result():
    requests = []
    task = {"session_id": "session-1", "task_id": "task-1"}

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"status": "ok", "result": task})

    client = _client(handler)
    try:
        assert await client.commit("session-1") == task
        assert len(requests) == 1
        request = requests[0]
        assert (request.method, request.url.path) == (
            "POST",
            "/api/v1/sessions/session-1/commit",
        )
        assert json.loads(request.content) == {"keep_recent_count": 0}
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_explicit_search_sends_namespace_and_preserves_hits(empty):
    requests = []
    memories = (
        []
        if empty
        else [
            {
                "uri": "viking://user/memories/preference.md",
                "abstract": "",
                "score": 0.9,
            },
        ]
    )

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"status": "ok", "result": {"memories": memories}},
        )

    client = _client(handler)
    try:
        assert (
            await client.search_memories(
                query="tea preference",
                max_results=3,
            )
            == memories
        )
        assert len(requests) == 1
        request = requests[0]
        assert (request.method, request.url.path) == (
            "POST",
            "/api/v1/search/search",
        )
        assert request.headers["X-API-Key"] == "test-tenant-key"
        assert json.loads(request.content) == {
            "query": "tea preference",
            "target_uri": "viking://~/memories",
            "context_type": "memory",
            "limit": 3,
            "mode": "list",
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_append_sends_completed_turn_metadata():
    requests = []
    messages = [
        {
            "role": "user",
            "content": "I prefer tea.",
            "turn_id": "turn-1",
            "message_kind": "user_query",
            "source_message_ids": ["message-1"],
        },
    ]

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"status": "ok", "result": {"added": 1}},
        )

    client = _client(handler)
    try:
        await client.add_messages("session-1", messages)
        assert len(requests) == 1
        request = requests[0]
        assert (request.method, request.url.path) == (
            "POST",
            "/api/v1/sessions/session-1/messages/batch",
        )
        assert json.loads(request.content) == {"messages": messages}
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_transport_failure_is_retryable_and_redacts_key(error_type):
    key = "transport-secret-key"

    def handler(request):
        raise error_type(f"failed with {key}", request=request)

    client = _client(handler, api_key=key)
    try:
        with pytest.raises(OpenVikingServiceError) as caught:
            await client.commit("session-1")
        assert "request failed" in str(caught.value)
        assert key not in str(caught.value)
        assert "<redacted>" in str(caught.value)
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_http_auth_failure_is_not_retryable(status):
    client = _client(lambda request: httpx.Response(status, text="denied"))
    try:
        with pytest.raises(OpenVikingConfigurationError):
            await client.commit("session-1")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_non_json_response_does_not_echo_body_or_key():
    key = "non-json-secret-key"
    client = _client(
        lambda request: httpx.Response(200, text=f"<html>{key}</html>"),
        api_key=key,
    )
    try:
        with pytest.raises(OpenVikingServiceError, match="non-JSON") as caught:
            await client.commit("session-1")
        assert key not in str(caught.value)
        assert "<html>" not in str(caught.value)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_redirect_never_forwards_key_to_another_host():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            307,
            headers={"Location": "https://other.test/collect"},
        )

    client = _client(handler)
    try:
        with pytest.raises(OpenVikingConfigurationError, match="HTTP 307"):
            await client.commit("session-1")
        assert len(requests) == 1
        assert requests[0].url.host == "openviking.test"
    finally:
        await client.close()

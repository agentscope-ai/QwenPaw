# -*- coding: utf-8 -*-
# pylint: disable=protected-access

import hashlib
import json

import httpx
import pytest

from plugins.memory.powercontext.backend.client import (
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
    assert hits[0]["citation"] == {
        "memory_ref": {
            "family": "memory",
            "artifact_id": "memory",
            "revision": 1,
        },
        "entry_id": "entry-1",
        "entry_version_id": "version-1",
    }
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


def _atomic_hit():
    return {
        "memory": {
            "artifact": {
                "family": "atomic-memory",
                "artifact_id": "am-123",
                "revision": 2,
            },
            "state_version": 0,
            "kind": "decision",
            "text": "Use the shared service.",
            "state": "active",
            "merged_into_id": None,
        },
        "score": 0.03,
        "matched_by": ["text", "vector"],
    }


@pytest.mark.asyncio
async def test_client_normalizes_atomic_search_without_fabricating_entry_ids():
    atomic_hit = _atomic_hit()
    # Atomic scores are raw RRF scores, without the legacy normalized range.
    atomic_hit["score"] = 1.5
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="project:x"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"hits": [atomic_hit]}),
        ),
        base_url="http://pc",
    )

    assert await client.search(query="choice") == [
        {
            "text": atomic_hit["memory"]["text"],
            "score": 1.5,
            "matched_by": ["text", "vector"],
            "citation": {
                "artifact": atomic_hit["memory"]["artifact"],
                "state_version": 0,
            },
        },
    ]
    await client.close()


@pytest.mark.asyncio
async def test_client_reuses_existing_scope_before_sending_memory():
    requests = []
    scope_id = "qwenpaw:existing/agent"

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"scope_id": scope_id})
        return httpx.Response(200, json={"hits": []})

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id=scope_id),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://pc",
    )

    assert await client.resolve_scope(create_default=True) == scope_id
    await client.search(query="choice")
    assert requests[0].url.raw_path == (
        b"/v1/scopes/qwenpaw%3Aexisting%2Fagent"
    )
    assert [request.method for request in requests] == ["GET", "POST"]
    assert json.loads(requests[1].content)["scope_id"] == scope_id
    await client.close()


@pytest.mark.asyncio
async def test_client_creates_default_scope_idempotently_and_uses_server_id():
    payloads = []
    memory_payloads = []
    legacy_id = "qwenpaw:installation:agent:test"
    actual_id = "scope-server-assigned"

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                404,
                json={"error": {"code": "scope_not_found"}},
            )
        payload = json.loads(request.content)
        if request.url.path == "/v1/scopes":
            payloads.append(payload)
            return httpx.Response(200, json={"scope_id": actual_id})
        memory_payloads.append(payload)
        return httpx.Response(200, json={"hits": []})

    # A fresh client models a restart where the host derives the same old ID.
    for _ in range(2):
        client = PowerContextMemoryClient(
            PowerContextConfig("http://pc", scope_id=legacy_id),
        )
        await client._http.aclose()
        client._http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://pc",
        )
        assert await client.resolve_scope(create_default=True) == actual_id
        assert client.config.scope_id == actual_id
        await client.remember(kind="fact", text="memory")
        await client.search(query="memory")
        await client.close()

    expected_payload = {
        "title": "QwenPaw agent memory",
        "summary": "Long-term memory for one QwenPaw installation and agent.",
        "idempotency_key": "qwenpaw-memory:"
        + hashlib.sha256(legacy_id.encode()).hexdigest(),
    }
    assert payloads == [expected_payload, expected_payload]
    assert all(payload["scope_id"] == actual_id for payload in memory_payloads)


@pytest.mark.asyncio
@pytest.mark.parametrize("create_status", [404, 409])
async def test_client_does_not_retry_scope_creation_with_another_key(
    create_status,
):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                404,
                json={"error": {"code": "scope_not_found"}},
            )
        return httpx.Response(
            create_status,
            json={"error": {"code": "scope_replay_failed"}},
        )

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="qwenpaw:installation"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://pc",
    )
    with pytest.raises(PowerContextHTTPError) as error:
        await client.resolve_scope(create_default=True)
    assert error.value.status_code == create_status
    assert [request.method for request in requests] == ["GET", "POST"]
    assert client.config.scope_id == "qwenpaw:installation"
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "create_default"),
    [(404, False), (404, True), (401, True), (403, True), (409, True)],
)
async def test_client_does_not_create_scope_after_access_or_explicit_errors(
    status,
    create_default,
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"message": "scope unavailable"})

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="project:explicit"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://pc",
    )
    with pytest.raises(PowerContextHTTPError) as error:
        await client.resolve_scope(create_default=create_default)
    assert error.value.status_code == status
    assert len(requests) == 1
    assert requests[0].method == "GET"
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("create_default", [False, True])
async def test_client_rejects_bad_scope_identity_without_echoing_response(
    create_default,
):
    def handler(request):
        if create_default and request.method == "GET":
            return httpx.Response(
                404,
                json={"error": {"code": "scope_not_found"}},
            )
        return httpx.Response(
            200,
            json={"scope_id": False, "text": "sensitive-scope-body"},
        )

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="project:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://pc",
    )
    with pytest.raises(PowerContextProtocolError) as error:
        await client.resolve_scope(create_default=create_default)
    assert "scope_id" in str(error.value)
    assert "sensitive-scope-body" not in str(error.value)
    assert client.config.scope_id == "project:test"
    await client.close()


@pytest.mark.asyncio
async def test_client_rejects_scope_lookup_returning_another_scope():
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="project:expected"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"scope_id": "project:another"},
            ),
        ),
        base_url="http://pc",
    )
    with pytest.raises(PowerContextProtocolError, match="scope_id"):
        await client.resolve_scope(create_default=True)
    await client.close()


@pytest.mark.asyncio
async def test_client_requires_successful_scope_lookup_before_using_identity():
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="project:expected"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                202,
                json={"scope_id": "project:expected"},
            ),
        ),
        base_url="http://pc",
    )
    with pytest.raises(PowerContextProtocolError, match="HTTP status"):
        await client.resolve_scope()
    await client.close()


@pytest.mark.asyncio
async def test_client_reports_nested_error_without_sensitive_details():
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", token="secret-token", scope_id="test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403,
                json={
                    "error": {
                        "code": "access_denied",
                        "message": (
                            "Caller secret-token cannot read the scope."
                        ),
                        "details": "sensitive-memory-body",
                        "context": {"body": "sensitive-scope-body"},
                    },
                },
            ),
        ),
        base_url="http://pc",
    )
    with pytest.raises(PowerContextHTTPError) as error:
        await client.resolve_scope(create_default=True)
    summary = str(error.value)
    assert "access_denied: Caller <redacted> cannot read the scope." in summary
    assert "sensitive" not in summary
    assert "secret-token" not in summary
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("memory", "artifact", "family"), "memory"),
        (("memory", "artifact", "revision"), True),
        (("memory", "state_version"), -1),
        (("memory", "state_version"), True),
        (("memory", "state"), "inactive"),
        (("memory", "merged_into_id"), "am-target"),
        (("memory", "text"), ""),
        (("memory", "kind"), ["decision"]),
        (("score",), True),
        (("score",), float("nan")),
        (("matched_by",), ["fts"]),
        (("matched_by",), [{"private-body": "sensitive"}]),
    ],
)
async def test_client_rejects_invalid_atomic_hits_without_echoing_content(
    field_path,
    value,
):
    hit = _atomic_hit()
    hit["memory"]["text"] = "private-body-should-not-appear-in-errors"
    target = hit
    for field in field_path[:-1]:
        target = target[field]
    target[field_path[-1]] = value
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="project:x"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=json.dumps({"hits": [hit]}),
                headers={"Content-Type": "application/json"},
            ),
        ),
        base_url="http://pc",
    )

    with pytest.raises(
        PowerContextProtocolError,
        match="hit 0.*invalid",
    ) as error:
        await client.search(query="choice")
    assert "private-body" not in str(error.value)
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


@pytest.mark.asyncio
async def test_prepare_context_preserves_unicode_and_assembly():
    requests = []
    content = "上下文\n" * 100
    envelope = {
        "schema": "powercontext.prepared-context.v1",
        "status": "ready",
        "content": content,
        "content_bytes": len(content.encode("utf-8")),
    }
    assembly = {"format": "markdown", "sections": [], "show": []}

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope)

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://pc",
    )
    result = await client.prepare_context(
        query="继续",
        max_bytes=1000,
        assembly=assembly,
    )
    assert result == envelope
    assert requests[0].url.path == "/v1/context/prepare"
    assert json.loads(requests[0].content) == {
        "scope_id": "agent:test",
        "query": "继续",
        "max_bytes": 1000,
        "assembly": assembly,
    }
    await client.close()


@pytest.mark.asyncio
async def test_prepare_context_empty_is_normal_and_assembly_is_optional():
    requests = []
    envelope = {
        "schema": "powercontext.prepared-context.v1",
        "status": "empty",
        "content": None,
        "content_bytes": 0,
    }

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope)

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://pc",
    )
    assert await client.prepare_context(query="x", max_bytes=512) == envelope
    assert "assembly" not in json.loads(requests[0].content)
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"schema": "unknown"},
        {"status": "skipped"},
        {"content": ""},
        {"content": " \n", "content_bytes": 2},
        {"content": None},
        {"content_bytes": True},
        {"content_bytes": 1},
        {"status": "empty", "content": "private", "content_bytes": 7},
        {"status": "empty", "content": None, "content_bytes": 1},
        {"extra": "private"},
        {"content": "你" * 171, "content_bytes": 513},
    ],
)
async def test_prepare_context_rejects_bad_envelopes_without_truncation(
    changes,
):
    envelope = {
        "schema": "powercontext.prepared-context.v1",
        "status": "ready",
        "content": "private",
        "content_bytes": 7,
    }
    envelope.update(changes)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope)

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://pc",
    )
    with pytest.raises(PowerContextProtocolError) as error:
        await client.prepare_context(query="x", max_bytes=512)
    assert "private" not in str(error.value)
    assert len(requests) == 1
    await client.close()


@pytest.mark.asyncio
async def test_prepare_context_preserves_meaningful_surrounding_whitespace():
    content = "\n 上下文 \n"
    envelope = {
        "schema": "powercontext.prepared-context.v1",
        "status": "ready",
        "content": content,
        "content_bytes": len(content.encode("utf-8")),
    }
    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=envelope),
        ),
        base_url="http://pc",
    )
    assert await client.prepare_context(query="x", max_bytes=512) == envelope
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": " "},
        {"query": True},
        {"query": "x" * 8193},
        {"max_bytes": 511},
        {"max_bytes": 32769},
        {"max_bytes": True},
        {"max_bytes": 512.0},
        {"assembly": []},
    ],
)
async def test_prepare_context_validates_request_before_network(kwargs):
    def handler(_request):
        pytest.fail("invalid input must not reach the server")

    client = PowerContextMemoryClient(
        PowerContextConfig("http://pc", scope_id="agent:test"),
    )
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://pc",
    )
    request = {"query": "x", "max_bytes": 512, **kwargs}
    with pytest.raises(PowerContextRequestValidationError):
        await client.prepare_context(**request)
    await client.close()

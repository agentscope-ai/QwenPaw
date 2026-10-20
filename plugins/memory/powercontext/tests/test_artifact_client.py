# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Observable HTTP contract for the unified Artifact client."""

import copy
import json

import httpx
import pytest

from plugins.memory.powercontext.backend.client import (
    PowerContextConfig,
    PowerContextHTTPError,
    PowerContextMemoryClient,
    PowerContextProtocolError,
    PowerContextRequestValidationError,
)

FAMILIES = {
    "atomic-memory": "AtomicMemory",
    "experience": "Experience",
    "skill": "Skill",
    "topic-memory": "TopicMemory",
    "handoff": "Handoff",
    "profile": "Profile",
    "prompt": "Prompt",
}


@pytest.fixture(name="client_factory")
async def make_client_factory():
    clients = []

    async def make(handler, scope_id="agent:test"):
        client = PowerContextMemoryClient(
            PowerContextConfig(
                "http://pc",
                token="secret-token",
                scope_id=scope_id,
            ),
        )
        await client._http.aclose()
        client._http = httpx.AsyncClient(
            base_url="http://pc",
            transport=httpx.MockTransport(handler),
        )
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.close()


def artifact(
    family="skill",
    artifact_id="a-1",
    revision=1,
    scope="agent:test",
):
    return {
        "scope_id": scope,
        "family": family,
        "artifact_id": artifact_id,
        "revision": revision,
        "content": {"title": "中文", "body": "完整内容" * 3000},
        "sources": [{"source_type": "content", "source_id": "s-1"}],
        "artifacts": [
            {"family": "experience", "artifact_id": "e-1", "revision": 3},
        ],
        "content_digest": "sha256:" + "a" * 64,
    }


def collection_item(**kwargs):
    record = artifact(**kwargs)
    record.pop("content")
    return record


def search_item(family="skill"):
    record = artifact(family=family)
    return {
        "family": record["family"],
        "artifact_id": record["artifact_id"],
        "revision": record["revision"],
        "content": record["content"],
        "lineage": {
            "sources": record["sources"],
            "artifacts": record["artifacts"],
        },
    }


@pytest.mark.parametrize(
    "family",
    ["atomic-memory", "experience", "skill", "topic-memory"],
)
async def test_artifact_search_preserves_full_results(client_factory, family):
    requests = []
    payload = {"results": [search_item(family)]}
    payload["results"][0]["scores"] = {
        "retrieval": 0.75,
        "channels": {},
    }

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    client = await client_factory(handler)
    assert (
        await client.artifact_search(
            family=family,
            query="上下文",
            limit=200,
            mode="hybrid",
            filters={"kind": "decision"},
            min_score=0.4,
            include_scores=True,
        )
        == payload
    )
    assert requests[0].url.path.endswith(f"/artifacts/{family}/search")
    assert json.loads(requests[0].content) == {
        "query": "上下文",
        "limit": 200,
        "mode": "hybrid",
        "filters": {"kind": "decision"},
        "min_score": 0.4,
        "include_scores": True,
    }


@pytest.mark.parametrize("family", FAMILIES)
async def test_artifact_create_and_replace_preserve_content_etags(
    client_factory,
    family,
):
    requests = []
    payload = artifact(family=family)

    def handler(request):
        requests.append(request)
        response = copy.deepcopy(payload)
        status = 201 if request.method == "POST" else 200
        if status == 201:
            response.pop("content")
            response.pop("content_digest")
        return httpx.Response(
            status,
            json=response,
            headers={"ETag": '"opaque+/=:etag"'},
        )

    client = await client_factory(handler)
    extra = {"prompt_key": "memory.extract"} if family == "prompt" else {}
    created = await client.artifact_create(
        family=family,
        content=payload["content"],
        **extra,
    )
    assert created["sources"] == payload["sources"]
    assert created["artifacts"] == payload["artifacts"]
    assert created["etag"] == '"opaque+/=:etag"'
    replaced = await client.artifact_replace(
        family=family,
        artifact_id="a-1",
        content=payload["content"],
        expected_etag=created["etag"],
    )
    assert replaced == {**payload, "etag": created["etag"]}
    assert requests[0].url.path == "/v1/scopes/agent:test/artifacts"
    assert json.loads(requests[0].content) == {
        "family": family,
        "content": payload["content"],
        **extra,
    }
    assert requests[1].method == "PUT"
    assert requests[1].headers["If-Match"] == created["etag"]
    assert json.loads(requests[1].content) == {"content": payload["content"]}


async def test_artifact_get_encodes_segments_and_exact_revision_has_no_etag(
    client_factory,
):
    requests = []
    scope = "project/a?#%"
    artifact_id = "a/b?#%"
    payload = artifact(scope=scope, artifact_id=artifact_id, revision=3)

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload, headers={"ETag": '"head"'})

    client = await client_factory(handler, scope_id=scope)
    assert await client.artifact_get(
        family="skill",
        artifact_id=artifact_id,
    ) == {**payload, "etag": '"head"'}
    assert (
        await client.artifact_get(
            family="skill",
            artifact_id=artifact_id,
            revision=3,
        )
        == payload
    )
    assert requests[0].url.raw_path == (
        b"/v1/scopes/project%2Fa%3F%23%25/artifacts/skill/a%2Fb%3F%23%25"
    )
    assert requests[1].url.raw_path.endswith(b"/revisions/3")


@pytest.mark.parametrize("method", ["artifact_list", "artifact_history"])
async def test_artifact_pagination_preserves_opaque_cursor(
    client_factory,
    method,
):
    requests = []
    cursor = "cursor+/=?中文"
    payload = {"items": [collection_item()], "next_cursor": cursor}

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    client = await client_factory(handler)
    kwargs = {"artifact_id": "a-1"} if method == "artifact_history" else {}
    result = await getattr(client, method)(
        family="skill",
        limit=100,
        cursor=cursor,
        **kwargs,
    )
    assert result == payload
    assert dict(requests[0].url.params) == {"limit": "100", "cursor": cursor}
    expected = "/artifacts/skill"
    if method == "artifact_history":
        expected += "/a-1/revisions"
    assert requests[0].url.path.endswith(expected)


@pytest.mark.parametrize(
    "changes",
    [
        {"scope_id": "another"},
        {"family": "experience"},
        {"artifact_id": "another"},
        {"revision": 2},
        {"revision": True},
        {"content": "private"},
        {"sources": {}},
        {"artifacts": None},
    ],
)
async def test_artifact_get_rejects_mismatched_identity_or_shape(
    client_factory,
    changes,
):
    payload = {**artifact(), **changes}
    client = await client_factory(
        lambda request: httpx.Response(200, json=payload),
    )
    with pytest.raises(PowerContextProtocolError) as error:
        await client.artifact_get(
            family="skill",
            artifact_id="a-1",
            revision=1,
        )
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": []},
        {"items": {}, "next_cursor": None},
        {"items": [], "next_cursor": 12},
        {"items": [collection_item(scope="another")], "next_cursor": None},
        {"items": [collection_item(family="prompt")], "next_cursor": None},
    ],
)
async def test_artifact_list_rejects_malformed_page(client_factory, payload):
    client = await client_factory(
        lambda request: httpx.Response(200, json=payload),
    )
    with pytest.raises(PowerContextProtocolError):
        await client.artifact_list(family="skill")


async def test_artifact_history_rejects_another_artifact(client_factory):
    client = await client_factory(
        lambda request: httpx.Response(
            200,
            json={
                "items": [collection_item(artifact_id="another")],
                "next_cursor": None,
            },
        ),
    )
    with pytest.raises(PowerContextProtocolError):
        await client.artifact_history(family="skill", artifact_id="a-1")


@pytest.mark.parametrize(
    "payload",
    [
        {"results": {}},
        {"results": [{**search_item(), "family": "prompt"}]},
        {"results": [{**search_item(), "revision": True}]},
        {"results": [{**search_item(), "lineage": None}]},
        {"results": [{**search_item(), "scope_id": "another"}]},
    ],
)
async def test_artifact_search_rejects_bad_identity(client_factory, payload):
    client = await client_factory(
        lambda request: httpx.Response(200, json=payload),
    )
    with pytest.raises(PowerContextProtocolError):
        await client.artifact_search(family="skill", query="x")


@pytest.mark.parametrize(
    "method",
    [
        "artifact_get",
        "artifact_create",
        "artifact_replace",
    ],
)
async def test_current_artifact_operations_require_etag(
    client_factory,
    method,
):
    client = await client_factory(
        lambda request: httpx.Response(
            201 if request.method == "POST" else 200,
            json=artifact(),
        ),
    )
    kwargs = {"family": "skill"}
    if method != "artifact_create":
        kwargs["artifact_id"] = "a-1"
    if method != "artifact_get":
        kwargs["content"] = {"body": "content"}
    if method == "artifact_replace":
        kwargs["expected_etag"] = '"old"'
    with pytest.raises(PowerContextProtocolError, match="ETag"):
        await getattr(client, method)(**kwargs)


@pytest.mark.parametrize("status", [401, 403, 409, 412, 422, 428, 503])
async def test_artifact_write_errors_are_redacted_and_not_retried(
    client_factory,
    status,
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={
                "error": {
                    "code": "write_failed",
                    "message": "secret-token rejected",
                    "details": "private content",
                },
            },
        )

    client = await client_factory(handler)
    with pytest.raises(PowerContextHTTPError) as error:
        await client.artifact_replace(
            family="skill",
            artifact_id="a-1",
            content={},
            expected_etag='"stale"',
        )
    assert error.value.status_code == status
    assert "secret-token" not in str(error.value)
    assert "private content" not in str(error.value)
    assert "<redacted>" in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("artifact_get", {"family": "memory", "artifact_id": "a-1"}),
        ("artifact_get", {"family": "skill", "artifact_id": "."}),
        ("artifact_get", {"family": "skill", "artifact_id": ".."}),
        (
            "artifact_get",
            {
                "family": "skill",
                "artifact_id": "a-1",
                "revision": True,
            },
        ),
        ("artifact_search", {"family": "handoff", "query": "x"}),
        ("artifact_search", {"family": "skill", "query": "x", "limit": 201}),
        ("artifact_search", {"family": "skill", "query": "x", "limit": True}),
        (
            "artifact_search",
            {
                "family": "skill",
                "query": "x",
                "include_scores": "yes",
            },
        ),
        (
            "artifact_search",
            {
                "family": "skill",
                "query": "x",
                "min_score": float("nan"),
            },
        ),
        ("artifact_search", {"family": "skill", "query": "x", "filters": []}),
        ("artifact_list", {"family": "skill", "limit": 101}),
        ("artifact_list", {"family": "skill", "cursor": ""}),
        ("artifact_create", {"family": "skill", "content": []}),
        (
            "artifact_create",
            {
                "family": "skill",
                "content": {},
                "prompt_key": "memory.extract",
            },
        ),
        ("artifact_create", {"family": "prompt", "content": {}}),
        (
            "artifact_replace",
            {
                "family": "skill",
                "artifact_id": "a-1",
                "content": {},
                "expected_etag": "*",
            },
        ),
        (
            "artifact_replace",
            {
                "family": "skill",
                "artifact_id": "a-1",
                "content": {},
                "expected_etag": " \t* ",
            },
        ),
        (
            "artifact_replace",
            {
                "family": "skill",
                "artifact_id": "a-1",
                "content": {},
                "expected_etag": "",
            },
        ),
    ],
)
async def test_artifact_invalid_request_never_reaches_network(
    client_factory,
    method,
    kwargs,
):
    def handler(_request):
        pytest.fail("invalid request must not reach the server")

    client = await client_factory(handler)
    with pytest.raises(PowerContextRequestValidationError):
        await getattr(client, method)(**kwargs)


@pytest.mark.parametrize("scope_id", [".", ".."])
async def test_artifact_scope_cannot_normalize_path(client_factory, scope_id):
    def handler(_request):
        pytest.fail("dot scope must not reach the server")

    client = await client_factory(handler, scope_id=scope_id)
    with pytest.raises(PowerContextRequestValidationError):
        await client.artifact_list(family="skill")


def schema_document(family):
    stem = FAMILIES[family]
    schemas = {
        f"Create{stem}ArtifactRequest": {
            "type": "object",
            "properties": {"content": {"$ref": "#/components/schemas/Body"}},
        },
        f"Replace{stem}ArtifactRequest": {
            "type": "object",
            "properties": {"content": {"$ref": "#/components/schemas/Body"}},
        },
        "Body": {
            "type": "object",
            "properties": {"child": {"$ref": "#/components/schemas/Body"}},
        },
        "Unrelated": {"type": "string"},
    }
    if family == "prompt":
        schemas["CreatePromptArtifactRequest"]["properties"]["prompt_key"] = {
            "$ref": "#/components/schemas/PromptKey",
        }
        schemas["PromptKey"] = {"enum": ["memory.extract"]}
    return {"openapi": "3.0.3", "components": {"schemas": schemas}}


@pytest.mark.parametrize("family", FAMILIES)
async def test_artifact_schema_returns_self_contained_cycle_safe_bundle(
    client_factory,
    family,
):
    document = schema_document(family)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=document)

    client = await client_factory(handler)
    bundle = await client.artifact_schema(family=family)
    stem = FAMILIES[family]
    schemas = document["components"]["schemas"]
    assert bundle["create"] == schemas[f"Create{stem}ArtifactRequest"]
    assert bundle["replace"] == schemas[f"Replace{stem}ArtifactRequest"]
    assert bundle["components"]["schemas"]["Body"] == schemas["Body"]
    assert "Unrelated" not in bundle["components"]["schemas"]
    if family == "prompt":
        assert bundle["components"]["schemas"]["PromptKey"] == {
            "enum": ["memory.extract"],
        }
    assert len(requests) == 1
    assert requests[0].url.path == "/openapi.json"


@pytest.mark.parametrize(
    "reference",
    [
        "https://elsewhere/private.json",
        "#/components/schemas/Missing",
        "#/paths/private",
    ],
)
async def test_artifact_schema_rejects_unresolved_refs_without_fetching_them(
    client_factory,
    reference,
):
    document = schema_document("skill")
    document["components"]["schemas"]["Body"] = {"$ref": reference}
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=document)

    client = await client_factory(handler)
    with pytest.raises(PowerContextProtocolError):
        await client.artifact_schema(family="skill")
    assert len(requests) == 1


async def test_artifact_schema_failure_does_not_poison_later_call(
    client_factory,
):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json=schema_document("skill"))

    client = await client_factory(handler)
    with pytest.raises(PowerContextHTTPError):
        await client.artifact_schema(family="skill")
    assert "create" in await client.artifact_schema(family="skill")
    assert len(requests) == 2

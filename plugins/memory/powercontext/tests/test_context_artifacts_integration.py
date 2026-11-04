# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Opt-in real-server acceptance for prepared context and Artifact tools."""

import json
import uuid

import pytest
from agentscope.message import ToolResultState

from .test_server_integration import (
    _message,
    _running_manager,
    _text,
)

# Register the opt-in disposable-server fixture in this test module.
# pylint: disable-next=unused-import
from .test_server_integration import disposable_server  # noqa: F401

pytestmark = pytest.mark.integration

FAMILIES = (
    "atomic-memory",
    "topic-memory",
    "experience",
    "skill",
    "profile",
    "prompt",
    "handoff",
)
SEARCHABLE = {"atomic-memory", "topic-memory", "experience", "skill"}


def _json_result(result):
    assert result.state == ToolResultState.SUCCESS, _text(result)
    text = _text(result)
    # Tools can prepend the common untrusted-history notice.
    return json.loads(text[text.index("{") :])


# Each family has a distinct public write contract.
# pylint: disable-next=too-many-return-statements
def _content(family, marker, *, source=None):
    if family == "atomic-memory":
        return {"kind": "decision", "text": f"{marker} preserves references."}
    if family == "topic-memory":
        return {
            "title": f"{marker} release",
            "summary": f"{marker} release checks.",
            "detail": f"{marker} checks the complete release contract.",
        }
    if family == "experience":
        return {
            "situation": f"{marker} required release checks.",
            "action": f"Test {marker} with the public API.",
            "outcome": f"{marker} passed verification.",
            "lesson": f"Verify {marker} before release.",
        }
    if family == "skill":
        return {
            "name": "release-check",
            "description": f"{marker} release checks.",
            "instructions": f"Run the {marker} contract checks.",
            "validation": ["The release checks pass."],
        }
    if family == "profile":
        return {"content": f"Prefers concise Chinese explanations. {marker}"}
    if family == "prompt":
        # Auto mode is supported even with no generation model configured.
        return {
            "schema_version": "powercontext.prompt.v1",
            "mode": "auto",
            "instructions": "",
            "demonstrations": [],
        }
    citation = {"kind": "source", "source_ref": source}
    return {
        "schema": "powercontext.handoff.v1",
        "objective": f"Complete {marker} verification.",
        "state": [
            {"text": "Verification is in progress.", "citations": [citation]},
        ],
        "disposition": "continuable",
        "next_action": {
            "text": "Run remaining checks.",
            "citations": [citation],
        },
        "omissions": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
# Keep each family's create, replacement, and exact-history checks together.
# pylint: disable-next=too-many-statements
async def test_artifact_tools_create_read_search_and_history(
    server,
    tmp_path,
    family,
):
    marker = "artifactacceptance" + uuid.uuid4().hex
    async with _running_manager(server, tmp_path / "host") as manager:
        assert hasattr(manager, "artifact_schema")
        schema = _json_result(await manager.artifact_schema(family))
        assert schema["create"]
        assert schema["replace"]
        assert isinstance(schema["components"]["schemas"], dict)
        source = None
        if family == "handoff":
            response = await server.post(
                "/v1/sources/content",
                json={
                    "scope_id": manager._scope_id(),
                    "source_id": marker,
                    "content": "Verification is in progress.",
                },
            )
            response.raise_for_status()
            source = response.json()["source"]
        content = _content(family, marker, source=source)
        created = _json_result(
            await manager.artifact_create(
                family,
                content,
                **(
                    {"prompt_key": "experience.generate"}
                    if family == "prompt"
                    else {}
                ),
            ),
        )
        assert created["family"] == family
        assert created["scope_id"] == manager._scope_id()
        assert created["revision"] == 1
        assert created["etag"]
        artifact_id = created["artifact_id"]
        current = _json_result(await manager.artifact_get(family, artifact_id))
        exact = _json_result(
            await manager.artifact_get(family, artifact_id, revision=1),
        )
        assert current["etag"] == created["etag"]
        assert exact["content"] == current["content"]
        assert exact["content_digest"] == current["content_digest"]
        assert exact["sources"] == current["sources"]
        assert exact["artifacts"] == current["artifacts"]
        if family != "prompt":
            assert marker in json.dumps(exact["content"], ensure_ascii=False)
        page = _json_result(await manager.artifact_list(family))
        assert artifact_id in {item["artifact_id"] for item in page["items"]}
        history = _json_result(
            await manager.artifact_history(family, artifact_id),
        )
        assert [item["revision"] for item in history["items"]] == [1]
        assert history["next_cursor"] is None
        if family in SEARCHABLE:
            found = _json_result(await manager.artifact_search(family, marker))
            assert artifact_id in {
                item["artifact_id"] for item in found["results"]
            }
        else:
            rejected = await manager.artifact_search(family, marker)
            assert rejected.state == ToolResultState.ERROR
        updated_marker = marker + "updated"
        updated = _json_result(
            await manager.artifact_replace(
                family,
                artifact_id,
                _content(family, updated_marker, source=source),
                expected_etag=current["etag"],
            ),
        )
        assert updated["revision"] == 2
        assert updated["etag"] != current["etag"]
        historical = _json_result(
            await manager.artifact_get(family, artifact_id, revision=1),
        )
        assert historical["content"] == exact["content"]
        new_head = _json_result(
            await manager.artifact_get(family, artifact_id),
        )
        assert new_head["revision"] == 2
        if family != "prompt":
            assert updated_marker in json.dumps(
                new_head["content"],
                ensure_ascii=False,
            )
        if family in SEARCHABLE:
            fresh = _json_result(
                await manager.artifact_search(family, updated_marker),
            )
            assert {
                (item["artifact_id"], item["revision"])
                for item in fresh["results"]
            } == {(artifact_id, 2)}
        # Prompt and Handoff are Scope-bound even though their IDs are stable.
        async with _running_manager(server, tmp_path / "other") as other:
            absent = await other.artifact_get(family, artifact_id)
            assert absent.state == ToolResultState.ERROR


@pytest.mark.asyncio
async def test_replacement_preserves_exact_history_and_rejects_stale_etag(
    server,
    tmp_path,
):
    async with _running_manager(server, tmp_path / "host") as manager:
        assert hasattr(manager, "artifact_create")
        original = _content("topic-memory", "original")
        created = _json_result(
            await manager.artifact_create("topic-memory", original),
        )
        artifact_id = created["artifact_id"]
        replacement = _content("topic-memory", "replacement")
        replaced = _json_result(
            await manager.artifact_replace(
                "topic-memory",
                artifact_id,
                replacement,
                expected_etag=created["etag"],
            ),
        )
        assert replaced["revision"] == 2
        assert replaced["etag"] != created["etag"]
        failed = await manager.artifact_replace(
            "topic-memory",
            artifact_id,
            _content("topic-memory", "stale"),
            expected_etag=created["etag"],
        )
        assert failed.state == ToolResultState.ERROR
        assert "412" in _text(failed)
        current = _json_result(
            await manager.artifact_get("topic-memory", artifact_id),
        )
        old = _json_result(
            await manager.artifact_get(
                "topic-memory",
                artifact_id,
                revision=1,
            ),
        )
        assert current["revision"] == 2
        assert current["content"] == replacement
        assert old["content"] == original
        first = _json_result(
            await manager.artifact_history(
                "topic-memory",
                artifact_id,
                limit=1,
            ),
        )
        second = _json_result(
            await manager.artifact_history(
                "topic-memory",
                artifact_id,
                limit=1,
                cursor=first["next_cursor"],
            ),
        )
        assert [
            first["items"][0]["revision"],
            second["items"][0]["revision"],
        ] == [
            2,
            1,
        ]
        assert second["next_cursor"] is None


@pytest.mark.asyncio
async def test_prepare_injects_four_families_with_exact_server_content(
    server,
    tmp_path,
):
    marker = "preparedacceptance" + uuid.uuid4().hex
    async with _running_manager(server, tmp_path / "host") as manager:
        assert hasattr(manager, "artifact_create")
        for family in (
            "atomic-memory",
            "topic-memory",
            "experience",
            "profile",
        ):
            _json_result(
                await manager.artifact_create(
                    family,
                    _content(family, marker),
                ),
            )
        # The matching term occurs beyond the old host's 50-character cap.
        query = ("!" * 60) + " " + marker
        incoming = _message("user", query)
        injected = await manager.auto_memory_search([incoming])
        assert injected is not None
        assert injected["query"] == query
        content = injected["text"]
        for heading in ("Profile", "Topic Memory", "Memory", "Experience"):
            assert f"## {heading}" in content
        options = await manager.get_auto_memory_search_options()
        search_config = manager._config.auto_memory_search_config
        budget = manager._auto_search_result_budget(
            query=query,
            max_results=options.max_results,
            max_context_bytes=search_config.max_context_bytes,
            estimate_divisor=options.estimate_divisor,
        )
        raw = await server.post(
            "/v1/context/prepare",
            json={
                "scope_id": manager._scope_id(),
                "query": query,
                "max_bytes": budget,
                "assembly": manager._config.context_assembly.model_dump(),
            },
        )
        raw.raise_for_status()
        assert content == raw.json()["content"]
        assert len(content.encode("utf-8")) == raw.json()["content_bytes"]
        assert len(content.encode("utf-8")) <= budget
        explicit = await manager.prepare_context(query, max_bytes=budget)
        assert explicit.state == ToolResultState.SUCCESS
        assert _text(explicit) == content
        calls = [
            block
            for block in injected["msg"][-1].content
            if getattr(block, "type", "") == "tool_call"
        ]
        assert len(calls) == 1
        assert calls[0].name == "prepare_context"
        assert json.loads(calls[0].input) == {
            "query": query,
            "max_bytes": budget,
        }
        result_blocks = [
            block
            for block in injected["msg"][-1].content
            if getattr(block, "type", "") == "tool_result"
        ]
        assert result_blocks
        assert result_blocks[0].output[0].text == content

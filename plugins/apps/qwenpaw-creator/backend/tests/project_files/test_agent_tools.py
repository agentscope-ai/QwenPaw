# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import hashlib
import inspect
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from services.project_files import agent_tools as agent_tools_module
from services.project_files.agent_tools import (
    AGENT_PROJECT_TOOL_SCHEMAS,
    _CUT_ADVISORY_SEEN,
    _PLAN_ADVISORY_SEEN,
    AgentProjectToolContext,
    AgentProjectToolError,
    AgentProjectTools,
    UnknownAgentProjectTool,
    agent_project_tool_manifest,
)
from services.project_files.commit import ProjectCommitBoundary
from services.project_files.models import (
    EditPlan,
    EditPlanDesignFloor,
    Project,
)

from .conftest import (
    commit_indexed_file,
    edit_element,
    make_store,
    read_state,
    review_boundary,
    spoken_edit_element,
    timeline_project_with,
)

pytestmark = pytest.mark.unit


def _context(**overrides):
    kwargs = {
        "origin": "runtime_task",
        "caused_by_request_id": "request-1",
        "caused_by_message_seq": 1,
    }
    kwargs.update(overrides)
    return AgentProjectToolContext(**kwargs)


def _tools(store, *, context=None):
    return AgentProjectTools(store, context=context or _context())


def _external_commit(store, base, **updates):
    candidate = base.project.model_dump(mode="json")
    candidate.update(updates)
    return (
        ProjectCommitBoundary(store)
        .commit(base=base, candidate=candidate, origin="frontend_edit")
        .snapshot
    )


def test_read_project_returns_and_privately_caches_the_real_base(tmp_path):
    store, base = make_store(tmp_path)
    tools = _tools(store)

    result = tools.read_project("project-1")
    assert result.project.project_id == "project-1"
    assert result.etag == base.etag

    # The returned model is a copy. Mutating a caller-owned result cannot alter
    # the private three-way-merge base held by the Runtime.
    result.project.name = "caller mutation"
    committed = tools.jq_project(
        project_id="project-1",
        program=".description = $description",
        string_args={"description": "Agent description"},
    )
    assert committed.project.name == "Initial"
    assert committed.project.description == "Agent description"
    assert committed.changed_pointers == ["/description"]


def test_cached_base_enables_base_candidate_latest_three_way_merge(tmp_path):
    store, base = make_store(tmp_path)
    tools = _tools(store)
    tools.read_project("project-1")
    _external_commit(store, base, description="User changed this concurrently")

    result = tools.jq_project(
        project_id="project-1",
        program=".name = $name",
        string_args={"name": "Agent name"},
    )

    assert result.generation == 2
    assert result.project.name == "Agent name"
    assert result.project.description == "User changed this concurrently"
    assert store.read("project-1").etag == result.etag


def test_jq_rejects_nested_object_with_protected_pointer_details(tmp_path):
    store, base = make_store(tmp_path)
    tools = _tools(store)
    tools.read_project("project-1")

    with pytest.raises(
        AgentProjectToolError,
        match="完整 Project 根对象",
    ) as caught:
        tools.jq_project(
            project_id="project-1",
            program='.timelines.items["timeline:main"]',
        )

    assert "/project_id" in str(caught.value)
    assert caught.value.code == "JQ_RESULT_NOT_PROJECT_ROOT"
    assert "/project_id" in caught.value.details["changedProtectedPointers"]
    assert store.read("project-1").etag == base.etag


def test_runtime_context_not_model_arguments_controls_review(tmp_path):
    store, base = make_store(tmp_path)
    context = _context(
        origin="agentdock_interrupt",
        review_policy="require_review",
        review_boundary=review_boundary(base),
        caused_by_request_id="request-2",
        caused_by_message_seq=2,
        round_id="agent-tool-round-2",
    )
    tools = _tools(store, context=context)
    observed = tools.read_project("project-1")
    assert observed.etag == base.etag

    result = tools.jq_project(
        project_id="project-1",
        program='.description = "review me"',
    )

    assert result.review_id == "review-agent-tool-round-2"
    state = read_state(store)
    assert state.accepted_generation == 0
    assert state.last_project_generation == 1


def test_manifest_and_invoke_expose_only_model_owned_arguments(tmp_path):
    schemas = AGENT_PROJECT_TOOL_SCHEMAS
    assert tuple(schemas) == (
        "read_project",
        "read_project_file",
        "jq_project",
        "patch_project",
        "elements_at",
    )
    jq_parameters = schemas["jq_project"]["parameters"]
    assert set(jq_parameters["properties"]) == {
        "projectId",
        "program",
        "stringArgs",
        "jsonArgs",
    }
    assert jq_parameters["required"] == ["projectId", "program"]
    assert jq_parameters["additionalProperties"] is False
    assert "完整 Project 根对象" in schemas["jq_project"]["description"]
    assert [
        item["function"]["name"] for item in agent_project_tool_manifest()
    ] == list(schemas)
    signature = inspect.signature(AgentProjectTools.jq_project)
    assert "origin" not in signature.parameters

    store, _base = make_store(tmp_path)
    tools = _tools(store)
    read = tools.invoke("read_project", {"projectId": "project-1"})
    written = tools.invoke(
        "jq_project",
        {
            "projectId": "project-1",
            # A deprecated baseEtag is tolerated and ignored; the Runtime
            # selects the base itself.
            "baseEtag": read["etag"],
            "program": ".name = $name | .settings.platform = $platform",
            "stringArgs": {"name": "Invoked", "platform": "web"},
        },
    )
    assert written["project"]["name"] == "Invoked"
    assert written["changedPointers"] == ["/name", "/settings/platform"]

    with pytest.raises(ValidationError, match="origin"):
        tools.invoke(
            "jq_project",
            {"projectId": "project-1", "program": ".", "origin": "task"},
        )
    with pytest.raises(UnknownAgentProjectTool):
        tools.invoke("write_project", {})


def test_invoke_translates_project_schema_errors_with_paths(tmp_path):
    store, base = make_store(tmp_path)
    tools = _tools(store)
    tools.invoke("read_project", {"projectId": "project-1"})

    with pytest.raises(AgentProjectToolError) as caught:
        tools.invoke(
            "jq_project",
            {
                "projectId": "project-1",
                "program": ('.visual.variants = {"items": {}, "order": []}'),
            },
        )
    message = str(caught.value)
    assert caught.value.code == "JQ_PROJECT_SCHEMA_INVALID"
    assert "visual.variants" in message
    assert "visual.entities.items" in message
    assert "项目未被修改" in message
    assert store.read("project-1").etag == base.etag


def test_read_project_file_pages_only_verified_indexed_utf8_text(tmp_path):
    store, base = make_store(tmp_path)
    content = "第一页：你好，Creator。\n第二页：文件索引。".encode()
    commit_indexed_file(
        store,
        base,
        file_id="file-story",
        kind="large_text",
        content=content,
        media_type="text/plain; charset=utf-8",
        relative_uri="assets/text/story.txt",
        staging_id="agent-read",
    )
    tools = _tools(store)

    # maxBytes=5 deliberately splits Chinese UTF-8 code points.
    args = {"projectId": "project-1", "fileId": "file-story", "maxBytes": 5}
    chunks: list[str] = []
    offset = 0
    while True:
        page = tools.invoke("read_project_file", {**args, "offset": offset})
        assert page["offset"] == offset
        assert page["sha256"] == hashlib.sha256(content).hexdigest()
        assert page["sizeBytes"] == len(content)
        assert len(page["content"].encode()) <= 5
        chunks.append(page["content"])
        offset = page["nextOffset"]
        if page["eof"]:
            break

    assert "".join(chunks).encode() == content
    assert offset == len(content)


def test_read_project_file_rejects_unknown_and_binary_files(tmp_path):
    store, base = make_store(tmp_path)
    commit_indexed_file(
        store,
        base,
        file_id="file-image",
        kind="artifact_payload",
        content=b"\x89PNG\r\n\x1a\n",
        media_type="image/png",
        relative_uri="assets/images/reference.png",
        staging_id="binary",
    )
    tools = _tools(store)

    with pytest.raises(AgentProjectToolError, match="does not exist"):
        tools.invoke(
            "read_project_file",
            {"projectId": "project-1", "fileId": "file-missing"},
        )
    with pytest.raises(AgentProjectToolError, match="not readable UTF-8 text"):
        tools.invoke(
            "read_project_file",
            {"projectId": "project-1", "fileId": "file-image"},
        )


# ── edit_plan / cut-boundary advisories (softened nudges) ───────────────────


def _advisory_tools(store):
    _PLAN_ADVISORY_SEEN.clear()
    _CUT_ADVISORY_SEEN.clear()
    return _tools(store, context=_context(round_id="agent-round-1"))


def _result(project: Project):
    return SimpleNamespace(project=project)


def test_plan_advisory_fires_until_plan_is_complete(tmp_path):
    store, base = make_store(tmp_path)
    tools = _advisory_tools(store)
    after = timeline_project_with(edit_element())

    advisory = tools._edit_plan_advisory(base.project, _result(after))

    assert advisory is not None
    assert advisory["kind"] == "edit_plan"
    hint = advisory["hints"][0]
    assert hint["timelineId"] == "timeline:main"
    assert hint["addedElementIds"] == ["el-edit-1"]
    assert "concept" in hint["missing"]
    assert "design_floor.opening" in hint["missing"]

    plan = EditPlan(
        concept="猫的越狱日记",
        pacing="hook 1.2s，动静交替",
        signature_device="爪印转场",
        design_floor=EditPlanDesignFloor(
            opening="1.5s 标题卡",
            transitions="硬切 + 爪印族",
            body="每场景一个设计节拍",
            ending="定格硬停",
        ),
    )
    planned = timeline_project_with(edit_element(), edit_plan=plan)
    tools = _advisory_tools(store)  # fresh dedup state
    assert tools._edit_plan_advisory(base.project, _result(planned)) is None


def test_cut_advisory_hints_off_boundary_endpoints(tmp_path, monkeypatch):
    store, base = make_store(tmp_path)
    tools = _advisory_tools(store)
    monkeypatch.setattr(
        agent_tools_module,
        "_transcript_boundaries_ms",
        lambda project, root, intelligence_id: (0, 5_000, 9_000),
    )
    # in=600ms is 600ms past the 0ms boundary (hint); out=5_100ms is
    # only 100ms from 5_000ms (inside tolerance, no hint).
    after = timeline_project_with(
        spoken_edit_element(in_tick=600, out_tick=5_100),
    )

    advisory = tools._cut_boundary_advisory(base.project, _result(after))

    assert advisory is not None
    assert advisory["kind"] == "cut_boundary"
    assert advisory["toleranceMs"] == 300
    assert len(advisory["hints"]) == 1
    hint = advisory["hints"][0]
    assert hint["endpoint"] == "in"
    assert hint["cutMs"] == 600
    assert hint["nearestSentenceBoundaryMs"] == 0
    assert "不阻断" in advisory["message"]

    # Identical findings are deduplicated on the next commit.
    again = tools._cut_boundary_advisory(base.project, _result(after))
    assert again is None

    # Human/front-end commits (no round_id) never receive the nudge.
    human = _tools(store)
    assert human._cut_boundary_advisory(base.project, _result(after)) is None

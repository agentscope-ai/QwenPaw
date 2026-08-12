# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import inspect

from pydantic import ValidationError
import pytest

from services.project_files.agent_tools import (
    AGENT_PROJECT_TOOL_SCHEMAS,
    AgentProjectToolContext,
    AgentProjectToolError,
    AgentProjectTools,
    UnknownAgentProjectTool,
    _translate_project_schema_error,
    agent_project_tool_manifest,
)
from services.project_files.assets import AssetFileStore
from services.project_files.commit import ProjectCommitBoundary
from services.project_files.json_pointer import JsonCasConflict
from services.project_files.models import (
    ElementLocation,
    IndexedFile,
    Project,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
)
from services.project_files.store import ProjectStore
from services.runtime_files.models import ReviewBoundary, RuntimeProjectState
from services.runtime_files.atomic_store import AtomicJsonRecordStore


pytestmark = pytest.mark.unit


def _store(tmp_path):
    store = ProjectStore(tmp_path.resolve())
    base = store.create(Project.new(project_id="project-1", name="Initial"))
    return store, base


def _tools(store, *, context=None):
    return AgentProjectTools(
        store,
        context=context
        or AgentProjectToolContext(
            origin="runtime_task",
            caused_by_request_id="request-1",
            caused_by_message_seq=1,
        ),
    )


def _external_commit(store, base, **updates):
    candidate = base.project.model_dump(mode="json")
    candidate.update(updates)
    return (
        ProjectCommitBoundary(store)
        .commit(
            base=base,
            candidate=candidate,
            origin="frontend_edit",
        )
        .snapshot
    )


def test_read_project_returns_and_privately_caches_the_real_base(tmp_path):
    store, base = _store(tmp_path)
    tools = _tools(store)

    result = tools.read_project("project-1")
    assert result.project.project_id == "project-1"
    assert result.generation == 0
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
    store, base = _store(tmp_path)
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


def test_jq_project_rejects_a_nested_object_instead_of_opaque_protected_diff(
    tmp_path,
):
    store, base = _store(tmp_path)
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


def test_cached_stale_base_still_detects_same_field_cas_conflict(tmp_path):
    store, base = _store(tmp_path)
    tools = _tools(store)
    tools.read_project("project-1")
    _external_commit(store, base, name="User name")

    with pytest.raises(JsonCasConflict):
        tools.jq_project(
            project_id="project-1",
            program=".name = $name",
            string_args={"name": "Agent name"},
        )


def test_first_contact_without_read_commits_against_the_latest_snapshot(
    tmp_path,
):
    store, old = _store(tmp_path)
    current = _external_commit(store, old, description="newer")

    # A boundary that never observed the Project selects the latest
    # snapshot itself; the model no longer echoes ETags.
    disconnected = _tools(store)
    result = disconnected.jq_project(
        project_id="project-1",
        program='.name = "reconnected"',
    )
    assert result.project.name == "reconnected"
    assert result.project.description == "newer"
    assert result.generation == current.generation + 1


def test_runtime_context_not_model_arguments_controls_review(tmp_path):
    store, base = _store(tmp_path)
    boundary = ReviewBoundary(
        request_message_seq=2,
        request_id="request-2",
        interrupted_run_id="run-1",
        accepted_generation=base.generation,
        accepted_etag=base.etag,
    )
    tools = _tools(
        store,
        context=AgentProjectToolContext(
            origin="agentdock_interrupt",
            review_policy="require_review",
            review_boundary=boundary,
            caused_by_request_id="request-2",
            caused_by_message_seq=2,
            round_id="agent-tool-round-2",
        ),
    )
    observed = tools.read_project("project-1")
    assert observed.etag == base.etag

    result = tools.jq_project(
        project_id="project-1",
        program='.description = "review me"',
    )

    assert result.review_id == "review-agent-tool-round-2"
    state = AtomicJsonRecordStore(
        tmp_path / "project-1" / "runtime" / "state.json",
        RuntimeProjectState,
    ).read()
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
    file_parameters = schemas["read_project_file"]["parameters"]
    assert set(file_parameters["properties"]) == {
        "projectId",
        "fileId",
        "offset",
        "maxBytes",
    }
    assert file_parameters["additionalProperties"] is False
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
    assert "jsonArgs" in schemas["jq_project"]["description"]
    assert "from_entries" in schemas["jq_project"]["description"]
    assert "拆分为少量几次调用" in schemas["jq_project"]["description"]
    elements_parameters = schemas["elements_at"]["parameters"]
    assert set(elements_parameters["properties"]) == {
        "projectId",
        "timelineId",
        "tick",
        "includeDisabled",
    }
    assert elements_parameters["additionalProperties"] is False
    assert [
        item["function"]["name"] for item in agent_project_tool_manifest()
    ] == [
        "read_project",
        "read_project_file",
        "jq_project",
        "patch_project",
        "elements_at",
    ]
    assert (
        "origin"
        not in inspect.signature(AgentProjectTools.jq_project).parameters
    )
    assert (
        "review_policy"
        not in inspect.signature(AgentProjectTools.jq_project).parameters
    )

    store, _base = _store(tmp_path)
    tools = _tools(store)
    read = tools.invoke("read_project", {"projectId": "project-1"})
    written = tools.invoke(
        "jq_project",
        {
            "projectId": "project-1",
            # A deprecated baseEtag from an older prompt/history is tolerated
            # and ignored; the Runtime selects the base itself.
            "baseEtag": read["etag"],
            "program": ".name = $name | .settings.platform = $platform",
            "stringArgs": {"name": "Invoked", "platform": "web"},
            "jsonArgs": {},
        },
    )
    assert written["project"]["name"] == "Invoked"
    assert written["changedPointers"] == ["/name", "/settings/platform"]

    with pytest.raises(ValidationError, match="origin"):
        tools.invoke(
            "jq_project",
            {
                "projectId": "project-1",
                "program": ".",
                "origin": "agentdock_interrupt",
            },
        )
    with pytest.raises(UnknownAgentProjectTool):
        tools.invoke("write_project", {})


def test_invoke_translates_misnested_program_arguments(tmp_path):
    store, _base = _store(tmp_path)
    tools = _tools(store)
    tools.invoke("read_project", {"projectId": "project-1"})

    with pytest.raises(AgentProjectToolError) as caught:
        tools.invoke(
            "jq_project",
            {
                "projectId": "project-1",
                "jsonArgs": {
                    "timeline_elements": {
                        "elem-01": {"name": "a"},
                        "elem-02": {
                            "name": "b",
                            "program": ". as $p",
                        },
                    },
                },
            },
        )
    message = str(caught.value)
    assert caught.value.code == "JQ_ARGUMENTS_MALFORMED"
    assert "花括号" in message
    assert "$.jsonArgs.timeline_elements.elem-02.program" in message
    assert "项目未被修改" in message


def test_invoke_translates_project_schema_errors_with_paths(tmp_path):
    store, base = _store(tmp_path)
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


def test_translate_schema_error_hints_root_level_visual_variant_binding():
    # Root-level model validators report an empty loc, so the hint must key
    # on the error message rather than the path prefix.
    raw = Project.new(project_id="project-1", name="Initial").model_dump(
        mode="json",
    )
    element = TimelineElement(
        element_id="element:hero",
        span=TimelineSpan(start_tick=0, duration_tick=1_000),
        location=ElementLocation(),
        creation=R2VCreation(
            visual_variant_refs={"char:ghost": "variant:x"},
        ),
    )
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "element:hero"
    ] = element.model_dump(mode="json")

    with pytest.raises(ValidationError) as caught:
        Project.model_validate(raw)
    message = _translate_project_schema_error(caught.value)

    assert "element element:hero" in message
    assert "unreferenced entity char:ghost" in message
    assert "character_refs/prop_refs/scene_ref" in message
    assert "先把实体加入引用列表" in message


def test_translate_schema_error_hints_missing_variant_binding():
    # The missing-variant branch must get its own hint, not the
    # unreferenced-entity guidance about character_refs.
    raw = Project.new(project_id="project-1", name="Initial").model_dump(
        mode="json",
    )
    raw["visual"]["entities"] = {
        "items": {
            "char:hero": {
                "entity_id": "char:hero",
                "kind": "character",
                "name": "Hero",
                "required_variant_ids": [],
            },
        },
        "order": ["char:hero"],
    }
    element = TimelineElement(
        element_id="element:hero",
        span=TimelineSpan(start_tick=0, duration_tick=1_000),
        location=ElementLocation(),
        creation=R2VCreation(
            character_refs=["char:hero"],
            visual_variant_refs={"char:hero": "variant:missing"},
        ),
    )
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "element:hero"
    ] = element.model_dump(mode="json")

    with pytest.raises(ValidationError) as caught:
        Project.model_validate(raw)
    message = _translate_project_schema_error(caught.value)

    assert "missing variant variant:missing" in message
    assert "先创建 Variant" in message
    assert "character_refs/prop_refs/scene_ref" not in message


def test_translate_schema_error_hints_misnested_element_fields():
    # A bracket slip put element-level fields inside creation: the three
    # resulting "Field required" errors must name the real mistake.
    raw = Project.new(project_id="project-1", name="Initial").model_dump(
        mode="json",
    )
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"]["elem:x"] = {
        "creation": {
            "type": "r2v",
            "element_id": "elem:x",
            "span": {"start_tick": 0, "duration_tick": 1000},
            "label": "错位",
        },
    }

    with pytest.raises(ValidationError) as caught:
        Project.model_validate(raw)
    message = _translate_project_schema_error(caught.value)

    assert "花括号层级错位" in message
    assert "提到与 creation 同级" in message


def test_read_project_file_pages_only_verified_indexed_utf8_text(tmp_path):
    store, base = _store(tmp_path)
    asset_store = AssetFileStore(store.project_root("project-1"))
    content = "第一页：你好，Creator。\n第二页：文件索引。".encode()
    relative_uri = "assets/text/story.txt"
    published = asset_store.publish(
        asset_store.stage_bytes(content, staging_id="agent-read"),
        relative_uri,
    )
    candidate = base.project.model_copy(deep=True)
    candidate.assets.files_by_id["file-story"] = IndexedFile(
        file_id="file-story",
        kind="large_text",
        relative_uri=published.relative_uri,
        sha256=published.sha256,
        size_bytes=published.size_bytes,
        media_type="text/plain; charset=utf-8",
        created_at=datetime.now(timezone.utc),
    )
    ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate.model_dump(mode="json"),
        origin="runtime_task",
    )
    tools = _tools(store)

    chunks: list[str] = []
    offset = 0
    while True:
        page = tools.invoke(
            "read_project_file",
            {
                "projectId": "project-1",
                "fileId": "file-story",
                # Deliberately split Chinese UTF-8 code points.
                "offset": offset,
                "maxBytes": 5,
            },
        )
        assert page["offset"] == offset
        assert page["sha256"] == hashlib.sha256(content).hexdigest()
        assert page["sizeBytes"] == len(content)
        assert page["mediaType"] == "text/plain; charset=utf-8"
        assert len(page["content"].encode()) <= 5
        chunks.append(page["content"])
        offset = page["nextOffset"]
        if page["eof"]:
            break

    assert "".join(chunks).encode() == content
    assert offset == len(content)


def test_read_project_file_rejects_unknown_and_binary_files(tmp_path):
    store, base = _store(tmp_path)
    asset_store = AssetFileStore(store.project_root("project-1"))
    content = b"\x89PNG\r\n\x1a\n"
    published = asset_store.publish(
        asset_store.stage_bytes(content, staging_id="binary"),
        "assets/images/reference.png",
    )
    candidate = base.project.model_copy(deep=True)
    candidate.assets.files_by_id["file-image"] = IndexedFile(
        file_id="file-image",
        kind="artifact_payload",
        relative_uri=published.relative_uri,
        sha256=published.sha256,
        size_bytes=published.size_bytes,
        media_type="image/png",
        created_at=datetime.now(timezone.utc),
    )
    ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate.model_dump(mode="json"),
        origin="runtime_task",
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


# ── edit_plan advisory (upstream plan_gate, softened) ───────────────────────


def _project_with_edit_element(*, edit_plan=None) -> Project:
    from services.project_files.models import EditCreation

    project = Project.new(project_id="project-1", name="Plan")
    timeline = project.timelines.items["timeline:main"]
    element = TimelineElement(
        element_id="el-edit-1",
        span=TimelineSpan(start_tick=0, duration_tick=1000),
        location=ElementLocation(),
        creation=EditCreation(intent="pick"),
    )
    updated = timeline.model_copy(
        update={
            "elements_by_id": {"el-edit-1": element},
            "edit_plan": edit_plan,
        },
    )
    patched = project.model_copy(deep=True)
    patched.timelines.items["timeline:main"] = updated
    return patched


def _advisory_tools(store):
    from services.project_files.agent_tools import (
        _CUT_ADVISORY_SEEN,
        _PLAN_ADVISORY_SEEN,
    )

    _PLAN_ADVISORY_SEEN.clear()
    _CUT_ADVISORY_SEEN.clear()
    return _tools(
        store,
        context=AgentProjectToolContext(
            origin="runtime_task",
            caused_by_request_id="request-1",
            caused_by_message_seq=1,
            round_id="agent-round-1",
        ),
    )


def _fake_commit_result(project: Project):
    from types import SimpleNamespace

    return SimpleNamespace(project=project)


def test_plan_advisory_fires_for_new_edit_without_plan(tmp_path):
    store, base = _store(tmp_path)
    tools = _advisory_tools(store)
    before = base.project
    after = _project_with_edit_element(edit_plan=None)

    advisory = tools._edit_plan_advisory(before, _fake_commit_result(after))

    assert advisory is not None
    assert advisory["kind"] == "edit_plan"
    hint = advisory["hints"][0]
    assert hint["timelineId"] == "timeline:main"
    assert hint["addedElementIds"] == ["el-edit-1"]
    assert "concept" in hint["missing"]
    assert "design_floor.opening" in hint["missing"]


def test_plan_advisory_silent_when_plan_is_complete(tmp_path):
    from services.project_files.models import (
        EditPlan,
        EditPlanDesignFloor,
    )

    store, base = _store(tmp_path)
    tools = _advisory_tools(store)
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
    after = _project_with_edit_element(edit_plan=plan)

    advisory = tools._edit_plan_advisory(
        base.project,
        _fake_commit_result(after),
    )

    assert advisory is None


# ── cut-boundary advisory (WT-B5 audio-first, softened) ───────────────────


def _project_with_spoken_edit(*, in_tick: int, out_tick: int) -> Project:
    from services.project_files.models import (
        EditCreation,
        SourceVersionRenderSource,
    )

    project = Project.new(project_id="project-1", name="Cut")
    timeline = project.timelines.items["timeline:main"]
    element = TimelineElement(
        element_id="el-edit-1",
        span=TimelineSpan(start_tick=0, duration_tick=out_tick - in_tick),
        location=ElementLocation(),
        creation=EditCreation(
            intent="pick",
            source_intelligence_version_id="intel-1",
        ),
        render_source=SourceVersionRenderSource(
            version_id="version-1",
            source_in_tick=in_tick,
            source_out_tick=out_tick,
        ),
    )
    updated = timeline.model_copy(
        update={"elements_by_id": {"el-edit-1": element}},
    )
    patched = project.model_copy(deep=True)
    patched.timelines.items["timeline:main"] = updated
    return patched


def test_cut_advisory_hints_endpoints_off_sentence_boundaries(
    tmp_path,
    monkeypatch,
):
    from services.project_files import agent_tools as agent_tools_module

    store, base = _store(tmp_path)
    tools = _advisory_tools(store)
    monkeypatch.setattr(
        agent_tools_module,
        "_transcript_boundaries_ms",
        lambda project, root, intelligence_id: (0, 5_000, 9_000),
    )
    # in=600ms is 600ms past the 0ms boundary (hint); out=5_100ms is
    # only 100ms from 5_000ms (inside tolerance, no hint).
    after = _project_with_spoken_edit(in_tick=600, out_tick=5_100)

    advisory = tools._cut_boundary_advisory(
        base.project,
        _fake_commit_result(after),
    )

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
    again = tools._cut_boundary_advisory(
        base.project,
        _fake_commit_result(after),
    )
    assert again is None


def test_cut_advisory_silent_without_speech_or_provenance(
    tmp_path,
    monkeypatch,
):
    from services.project_files import agent_tools as agent_tools_module

    store, base = _store(tmp_path)
    tools = _advisory_tools(store)
    # Pure-BGM source: no transcript boundaries → no hint at all.
    monkeypatch.setattr(
        agent_tools_module,
        "_transcript_boundaries_ms",
        lambda project, root, intelligence_id: (),
    )
    after = _project_with_spoken_edit(in_tick=600, out_tick=5_100)
    assert (
        tools._cut_boundary_advisory(base.project, _fake_commit_result(after))
        is None
    )

    # Snapped endpoints stay silent even with a transcript.
    monkeypatch.setattr(
        agent_tools_module,
        "_transcript_boundaries_ms",
        lambda project, root, intelligence_id: (0, 5_000),
    )
    snapped = _project_with_spoken_edit(in_tick=100, out_tick=4_900)
    assert (
        tools._cut_boundary_advisory(
            base.project,
            _fake_commit_result(snapped),
        )
        is None
    )

    # Human/front-end commits (no round_id) never receive the nudge.
    human = _tools(store)
    assert (
        human._cut_boundary_advisory(base.project, _fake_commit_result(after))
        is None
    )

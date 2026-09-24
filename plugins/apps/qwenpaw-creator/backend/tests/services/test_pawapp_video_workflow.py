# -*- coding: utf-8 -*-
"""Contract and durable bootstrap tests for Creator create-video."""

import asyncio
from datetime import timedelta
import hashlib
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from domain.enums import (
    CreatorGoalStatus,
    SpecialistRole,
    TaskKind,
    TaskStatus,
)
from services import pawapp_video_workflow
from services.file_agent_runtime.models import (
    AgentRunStatus,
    CreatorAgentRunRecord,
)
from services.file_agent_runtime.run_store import CreatorAgentRunStore
from services.file_agent_runtime.work_graph import (
    WorkGraph,
    WorkNode,
    WorkNodeStatus,
    dispatch_ledger_fingerprint,
    dispatch_model_scope,
    dispatch_slot,
)
from services.pawapp_video_workflow import (
    CREATOR_VIDEO_GOAL_MAPPING_VERSION,
    CREATOR_VIDEO_WORKFLOW_EXECUTOR_ID,
    CreatorVideoWorkflowEvent,
    CreatorVideoWorkflowStage,
    CreatorVideoWorkflowSubmission,
    CreatorVideoWorkflowTaskAdapter,
    creator_create_video_action_descriptor,
    creator_video_goal_digest_v1,
    derive_creator_video_project_name,
    normalize_creator_video_workflow_input,
    render_creator_video_goal_v1,
)
from services.project_files.assets import AssetFileStore
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    IndexedFile,
    Timeline,
    narrative_timeline_ids,
)
from services.runtime_files.execution_models import (
    ExecutionAuthorizationRecord,
    ExecutionAuthorizationStatus,
    SpecialistRunRecord,
    SpecialistRunStatus,
    TaskRecord,
)
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.models import ChangeOrigin, ReviewPolicy, utc_now
from qwenpaw.pawapp.artifacts import MAX_ARTIFACT_BYTES, ArtifactStore
from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    ExecutorRunRef,
    TaskCommand,
    TaskHandle,
    TaskOrigin,
    TaskScope,
    TaskStore,
    TaskStoreError,
    TaskSubmission,
)
from qwenpaw.pawapp.tasks.contracts import content_digest
from qwenpaw.pawapp.tasks.runtime import _ReadyAdapter

pytestmark = pytest.mark.unit


def test_create_video_descriptor_is_the_complete_public_contract() -> None:
    descriptor = creator_create_video_action_descriptor()
    fixture_path = (
        Path(__file__).resolve().parents[6]
        / "docs/design/pawapp-vnext-creator-create-video-action.example.json"
    )

    assert descriptor == ActionDescriptor.model_validate_json(
        fixture_path.read_text(encoding="utf-8"),
    )
    assert descriptor.model_dump(mode="json") == {
        "schema_version": 1,
        "app_id": "qwenpaw-creator",
        "action_id": "create-video",
        "summary": (
            "Unlike create-project, which creates an empty project, "
            "create-video creates a Creator project, builds a production "
            "plan from the brief and optional script, pauses for required "
            "setup and generation approval, renders and publishes the final "
            "video, and returns the project and result."
        ),
        "engagements": ["delegated"],
        "input_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 8000,
                    "pattern": r"\S",
                },
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                    "pattern": r"\S",
                },
                "script": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 50000,
                    "pattern": r"\S",
                },
                "description": {
                    "type": "string",
                    "maxLength": 2000,
                    "default": "",
                },
                "scenario": {
                    "type": "string",
                    "enum": ["short_drama", "video_edit", "general"],
                    "default": "general",
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["16:9", "9:16", "1:1", "4:3", "3:4"],
                    "default": "16:9",
                },
                "resolution": {
                    "type": "string",
                    "enum": ["720P", "1080P"],
                    "default": "720P",
                },
                "content_type": {
                    "type": "string",
                    "enum": [
                        "pet_video",
                        "gaming",
                        "sports",
                        "travel_vlog",
                        "interview",
                        "general",
                    ],
                },
                "duration_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3600,
                },
                "language": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 35,
                    "pattern": (r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$"),
                    "default": "zh-CN",
                },
            },
            "required": ["brief"],
            "additionalProperties": False,
        },
        "output_types": ["text/plain", "qwenpaw:file"],
        "permissions": [
            "creator.project.create",
            "creator.project.read",
            "creator.project.write",
            "creator.image.generate",
            "creator.video.generate",
        ],
        "effects": ["model_usage", "project_mutation"],
        "adapter_ref": "qwenpaw-creator.video-workflow.v1",
    }


def test_normalization_applies_defaults_and_preserves_internal_text() -> None:
    normalized = normalize_creator_video_workflow_input(
        {
            "brief": " \r\n First   line \rSecond line\twith tab \r\n ",
            "name": " \r\n My  project \r ",
            "script": " \r\nScene 1:\r\n  Keep  two spaces.\rScene 2. \r\n ",
            "description": " \r Description  text \r\n ",
            "scenario": " general\r\n",
            "aspect_ratio": " 16:9 ",
            "resolution": "\r720P\n",
            "content_type": " general ",
            "language": " zh-CN\r\n",
        },
    )

    assert normalized.model_dump(mode="json") == {
        "brief": "First   line \nSecond line\twith tab",
        "name": "My  project",
        "script": "Scene 1:\n  Keep  two spaces.\nScene 2.",
        "description": "Description  text",
        "scenario": "general",
        "aspect_ratio": "16:9",
        "resolution": "720P",
        "content_type": "general",
        "duration_seconds": None,
        "language": "zh-CN",
    }

    defaults = normalize_creator_video_workflow_input({"brief": "Make it"})
    assert defaults.model_dump(mode="json") == {
        "brief": "Make it",
        "name": None,
        "script": None,
        "description": "",
        "scenario": "general",
        "aspect_ratio": "16:9",
        "resolution": "720P",
        "content_type": None,
        "duration_seconds": None,
        "language": "zh-CN",
    }
    assert (
        normalize_creator_video_workflow_input(
            {"brief": "Make it", "description": " \r\n\t "},
        ).description
        == ""
    )


def test_derived_name_uses_unicode_limit_and_submission_hash() -> None:
    normalized = normalize_creator_video_workflow_input(
        {"brief": ("猫 " * 60) + "\nignored second line"},
    )

    name = derive_creator_video_project_name(normalized, "submission-123")
    prefix, suffix = name.rsplit("-", 1)

    assert suffix == "c38c010f9891"
    assert len(prefix) == 95
    assert len(prefix) <= 96
    assert not prefix.endswith(" ")
    assert len(name) <= 120
    assert name == derive_creator_video_project_name(
        normalized,
        "submission-123",
    )

    collapsed = normalize_creator_video_workflow_input(
        {"brief": " Readable\t  title   here\nignored second line"},
    )
    assert (
        derive_creator_video_project_name(
            collapsed,
            "submission-123",
        )
        == "Readable title here-c38c010f9891"
    )

    explicit = normalize_creator_video_workflow_input(
        {"brief": "Ignored", "name": " Exact  supplied name "},
    )
    assert (
        derive_creator_video_project_name(explicit, "another-submission")
        == "Exact  supplied name"
    )


def test_rendered_v1_goal_and_digest_are_exact() -> None:
    normalized = normalize_creator_video_workflow_input(
        {
            "brief": "  Launch story\r\nwith exact  spacing  ",
            "script": "  Scene 1:\r\n  Keep  two spaces.  ",
            "scenario": "short_drama",
            "aspect_ratio": "9:16",
            "resolution": "1080P",
            "duration_seconds": 90,
            "language": "en-US",
        },
    )

    goal = render_creator_video_goal_v1(normalized, "submission-123")

    assert CREATOR_VIDEO_GOAL_MAPPING_VERSION == 1
    assert goal == (
        "[creator-video-workflow@1]\n"
        "Submission: submission-123\n"
        "\n"
        "Brief:\n"
        "Launch story\n"
        "with exact  spacing\n"
        "\n"
        "User script:\n"
        "Scene 1:\n"
        "  Keep  two spaces.\n"
        "\n"
        "Production constraints:\n"
        "- project_name: Launch story-c38c010f9891\n"
        "- description: Not provided.\n"
        "- scenario: short_drama\n"
        "- aspect_ratio: 9:16\n"
        "- resolution: 1080P\n"
        "- content_type: Not specified.\n"
        "- duration_seconds: 90\n"
        "- language: en-US\n"
        "- completion: publish one final composed video"
    )
    assert not goal.endswith("\n")
    assert (
        creator_video_goal_digest_v1(
            normalized,
            "submission-123",
        )
        == "898d9716d673d649f0a47d818a74a2827a6dc9c6f5f798b2667d8f2d040bea17"
    )


def test_rendered_v1_goal_uses_all_missing_value_phrases() -> None:
    normalized = normalize_creator_video_workflow_input({"brief": "Video"})

    goal = render_creator_video_goal_v1(normalized, "submission-123")

    assert "Not provided; create a script from the brief." in goal
    assert "- description: Not provided." in goal
    assert "- content_type: Not specified." in goal
    assert "- duration_seconds: Not specified." in goal


@pytest.mark.parametrize("duration", [1.0, True, False, 0, 3601])
def test_normalization_rejects_non_strict_or_out_of_range_duration(
    duration: object,
) -> None:
    with pytest.raises(ValidationError):
        normalize_creator_video_workflow_input(
            {"brief": "Video", "duration_seconds": duration},
        )


def test_json_schema_does_not_replace_strict_duration_normalization() -> None:
    descriptor = creator_create_video_action_descriptor()
    descriptor.validate_inputs({"brief": "Video", "duration_seconds": 1.0})

    with pytest.raises(ValidationError):
        normalize_creator_video_workflow_input(
            {"brief": "Video", "duration_seconds": 1.0},
        )


@pytest.mark.parametrize(
    "language",
    ["z", "en_US", "en-", "en--US", "zh-中文", "toolonglanguage"],
)
def test_normalization_rejects_malformed_language(language: str) -> None:
    with pytest.raises(ValidationError):
        normalize_creator_video_workflow_input(
            {"brief": "Video", "language": language},
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("brief", " \r\n\t "),
        ("name", " \r\n\t "),
        ("script", " \r\n\t "),
    ],
)
def test_normalization_rejects_whitespace_only_text(
    field: str,
    value: str,
) -> None:
    payload = {"brief": "Video", field: value}
    with pytest.raises(ValidationError):
        normalize_creator_video_workflow_input(payload)


@pytest.mark.parametrize(
    "field",
    [
        "project_id",
        "target_ref",
        "timeline_id",
        "element_id",
        "work_node_id",
        "provider_job_id",
        "credential_id",
        "source_upload_id",
        "template_id",
        "execution_preauthorization",
        "clientRequestId",
        "unknown",
    ],
)
def test_normalization_rejects_internal_and_unknown_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        normalize_creator_video_workflow_input(
            {"brief": "Video", field: "not-public"},
        )

    with pytest.raises(ValueError, match="invalid action input"):
        creator_create_video_action_descriptor().validate_inputs(
            {"brief": "Video", field: "not-public"},
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("brief", "x" * 8001),
        ("name", "x" * 121),
        ("script", "x" * 50001),
        ("description", "x" * 2001),
        ("language", "a" * 36),
    ],
)
def test_normalization_rejects_oversized_strings(
    field: str,
    value: str,
) -> None:
    payload = {"brief": "Video", field: value}
    with pytest.raises(ValidationError):
        normalize_creator_video_workflow_input(payload)


def test_goal_digest_uses_canonical_content_digest() -> None:
    normalized = normalize_creator_video_workflow_input({"brief": "Video"})
    goal = render_creator_video_goal_v1(normalized, "submission-123")

    assert creator_video_goal_digest_v1(
        normalized,
        "submission-123",
    ) == content_digest(goal)


def _services(tmp_path: Path) -> CreatorFileServices:
    return CreatorFileServices.create(tmp_path.resolve())


def _submission(
    submission_id: str = "create-video-submission-1",
    *,
    task_id: str = "host-create-video-task-1",
    inputs: dict | None = None,
    executor_sequence: int | None = None,
) -> TaskSubmission:
    descriptor = creator_create_video_action_descriptor()
    return TaskSubmission(
        handle=TaskHandle(
            task_id=task_id,
            submission_id=submission_id,
            scope=TaskScope(
                principal_id="alice",
                workspace_id="workspace-1",
                app_id="qwenpaw-creator",
            ),
            action_id=descriptor.action_id,
            descriptor_digest=descriptor.descriptor_digest,
            origin=TaskOrigin(
                engagement="delegated",
                origin_ref="chat-1",
                return_session_ref="chat-1",
            ),
            executor_sequence=executor_sequence,
            created_at=1000,
            updated_at=1000,
        ),
        action=descriptor,
        inputs=inputs or {"brief": "Create a calm launch video."},
    )


def _accepted_submission(
    submission: TaskSubmission,
    run_ref: ExecutorRunRef,
    *,
    executor_sequence: int | None = None,
) -> TaskSubmission:
    return submission.model_copy(
        update={
            "handle": submission.handle.model_copy(
                update={
                    "executor_run_ref": run_ref,
                    "executor_sequence": executor_sequence,
                },
            ),
        },
    )


def _workflow_record(
    services: CreatorFileServices,
    submission_id: str,
) -> CreatorVideoWorkflowSubmission:
    return CreatorVideoWorkflowTaskAdapter._store(
        services,
        submission_id,
    ).read()


def _agent_run(
    services: CreatorFileServices,
    record: CreatorVideoWorkflowSubmission,
    *,
    run_id: str = "agent-run-1",
    status: AgentRunStatus = AgentRunStatus.RUNNING,
    error: dict | None = None,
    goal_id: str | None = None,
    message_id: str | None = None,
    message_seq: int | None = None,
) -> CreatorAgentRunRecord:
    message = next(
        item
        for item in services.sessions.list_messages(
            record.project_id,
            record.creator_session_id,
        )
        if item.message_id == (message_id or record.initial_message_id)
    )
    snapshot = services.projects.read(record.project_id)
    store = CreatorAgentRunStore(services.root)
    created = store.create(
        CreatorAgentRunRecord(
            run_id=run_id,
            project_id=record.project_id,
            session_id=record.creator_session_id,
            goal_id=goal_id or record.goal_id,
            conversation_id=record.conversation_id,
            round_id=f"round-{run_id}",
            caused_by_message_id=message_id or message.message_id,
            caused_by_message_seq=message_seq or message.message_seq,
            origin=ChangeOrigin.AGENTDOCK_IDLE_GOAL,
            review_policy=ReviewPolicy.AUTO_FIX,
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
        ),
    )
    if status is AgentRunStatus.RUNNING:
        return store.transition(
            record.project_id,
            run_id,
            expected_status=AgentRunStatus.QUEUED,
            status=status,
        )
    if status is AgentRunStatus.SUCCEEDED:
        store.transition(
            record.project_id,
            run_id,
            expected_status=AgentRunStatus.QUEUED,
            status=AgentRunStatus.RUNNING,
        )
        return store.transition(
            record.project_id,
            run_id,
            expected_status=AgentRunStatus.RUNNING,
            status=status,
        )
    if status in {AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
        return store.transition(
            record.project_id,
            run_id,
            expected_status=AgentRunStatus.QUEUED,
            status=status,
            updates={"error": error} if error is not None else None,
        )
    return created


def _authorization(
    services: CreatorFileServices,
    record: CreatorVideoWorkflowSubmission,
    run: CreatorAgentRunRecord,
    authorization_id: str = "authorization-1",
    **overrides,
) -> ExecutionAuthorizationRecord:
    authorization = ExecutionAuthorizationRecord(
        authorization_id=authorization_id,
        project_id=record.project_id,
        round_id=run.round_id,
        run_id=run.run_id,
        execution_request_id=f"execution-{authorization_id}",
        operation="r2v_generation",
        target_scope=["element:internal-shot-id"],
        authorization_token=f"secret-{authorization_id}",
        summary="Internal prompt and target details must not be exposed.",
        scope={
            "parameters": {
                "durationSeconds": 5,
                "resolution": "1080p",
                "ratio": "9:16",
                "mode": "fast",
                "generateAudio": True,
                "prompt": "hidden raw generation prompt",
            },
        },
        requested_provider="video-provider",
        requested_model="video-model",
        requested_candidates=2,
    )
    if overrides:
        authorization = authorization.model_copy(update=overrides)
    return ProjectExecutionStore(
        services.root,
    ).create_execution_authorization(authorization)


async def _query_after_deferred_setup_check(
    adapter: CreatorVideoWorkflowTaskAdapter,
    services: CreatorFileServices,
    submission: TaskSubmission,
) -> TaskSubmission:
    await adapter.query(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    setup_event = record.events[-1]
    assert setup_event.setup_requirement_id is not None
    resumed = submission.model_copy(
        update={
            "handle": submission.handle.model_copy(
                update={"executor_sequence": setup_event.sequence},
            ),
        },
    )
    await adapter.query(resumed)
    return resumed


def _answer_command(
    submission: TaskSubmission,
    request_id: str,
    label: str,
    *,
    command_id: str = "answer-1",
) -> TaskCommand:
    return TaskCommand(
        task_id=submission.handle.task_id,
        command_id=command_id,
        kind="answer",
        request_id=request_id,
        payload={
            "answers": [
                {
                    "question": "Run this Creator generation operation once?",
                    "selected_options": [label],
                },
            ],
        },
        created_at=1001,
        updated_at=1001,
    )


def _graph(*nodes: WorkNode) -> WorkGraph:
    return WorkGraph(nodes=nodes, generation=1)


def _node(
    kind: str,
    status: WorkNodeStatus,
    *,
    task_id: str | None = None,
) -> WorkNode:
    return WorkNode(
        node_id=f"{kind}-node",
        kind=kind,
        label=f"{kind} work",
        status=status,
        task_id=task_id,
        command="TEST_COMMAND" if status is WorkNodeStatus.READY else None,
        target_ref=f"{kind}:target",
        regeneration_of=(
            "artifact-version:old" if status is WorkNodeStatus.STALE else None
        ),
    )


def _install_final_video(
    services: CreatorFileServices,
    record: CreatorVideoWorkflowSubmission,
    run: CreatorAgentRunRecord,
    suffix: str,
) -> tuple[WorkGraph, bytes]:
    snapshot = services.projects.read(record.project_id)
    timeline_ids = narrative_timeline_ids(snapshot.project)
    assert len(timeline_ids) == 1
    timeline_id = timeline_ids[0]
    content = f"final-video-{suffix}".encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    relative_uri = f"assets/artifacts/final-{suffix}.mp4"
    files = AssetFileStore(services.projects.project_root(record.project_id))
    files.publish(
        files.stage_bytes(content, staging_id=f"final-{suffix}"),
        relative_uri,
        expected_sha256=digest,
        expected_size_bytes=len(content),
    )

    task_id = f"compose-task-{suffix}"
    specialist_run_id = f"compose-run-{suffix}"
    compose_fingerprint = f"compose-fingerprint-{suffix}"
    render_fingerprint = f"sha256:render-fingerprint-{suffix}"
    compose_ledger = dispatch_ledger_fingerprint(
        compose_fingerprint,
        dispatch_model_scope("compose", ("", "")),
    )
    dispatch_key = (
        f"dag-compose:{timeline_id}-{dispatch_slot(compose_ledger)}"
    )
    read_set = [{"ref": f"artifact-version:source-{suffix}"}]
    source_selections = [{"elementId": f"shot-{suffix}"}]
    executions = ProjectExecutionStore(services.root)
    executions.create_specialist_run(
        SpecialistRunRecord(
            run_id=specialist_run_id,
            project_id=record.project_id,
            round_id=f"compose-round-{suffix}",
            role=SpecialistRole.AI_EDITING_DIRECTOR,
            target_refs=[f"timeline:{timeline_id}"],
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            related_run_id=run.run_id,
            caused_by_request_id=dispatch_key,
        ),
    )
    executions.create_task(
        TaskRecord(
            task_id=task_id,
            project_id=record.project_id,
            round_id=f"compose-round-{suffix}",
            run_id=specialist_run_id,
            kind=TaskKind.COMPOSE,
            request_fingerprint=render_fingerprint,
            idempotency_key=dispatch_key,
            caused_by_request_id=dispatch_key,
            read_set=read_set,
            metadata={
                "commandType": "COMPOSE_FINAL_VIDEO",
                "targetRef": f"timeline:{timeline_id}",
            },
        ),
    )
    executions.transition_task(
        record.project_id,
        task_id,
        expected_status="QUEUED",
        status="RUNNING",
    )
    executions.transition_task(
        record.project_id,
        task_id,
        expected_status="RUNNING",
        status="SUCCEEDED",
    )
    executions.transition_specialist_run(
        record.project_id,
        specialist_run_id,
        expected_status=SpecialistRunStatus.QUEUED,
        status=SpecialistRunStatus.RUNNING_MODEL,
    )
    executions.transition_specialist_run(
        record.project_id,
        specialist_run_id,
        expected_status=SpecialistRunStatus.RUNNING_MODEL,
        status=SpecialistRunStatus.SUCCEEDED,
    )

    file_id = f"file-final-{suffix}"
    version_id = f"version-final-{suffix}"
    slot_id = f"timeline:{timeline_id}:render"
    now = utc_now()
    candidate = snapshot.project.model_copy(deep=True)
    candidate.assets.files_by_id[file_id] = IndexedFile(
        file_id=file_id,
        kind="artifact_payload",
        relative_uri=relative_uri,
        sha256=digest,
        size_bytes=len(content),
        media_type="video/mp4",
        created_at=now,
    )
    slot = candidate.assets.artifact_slots_by_id.get(slot_id)
    if slot is None:
        slot = ArtifactSlot(
            slot_id=slot_id,
            kind="final_video",
            owner_ref=f"timeline:{timeline_id}",
            version_ids=[],
        )
        candidate.assets.artifact_slots_by_id[slot_id] = slot
    slot.version_ids.append(version_id)
    slot.selected_version_id = version_id
    candidate.assets.artifact_versions_by_id[version_id] = ArtifactVersion(
        version_id=version_id,
        slot_id=slot_id,
        kind="final_video",
        owner_ref=f"timeline:{timeline_id}",
        name=f"Final {suffix}",
        file_id=file_id,
        checksum=digest,
        based_on_generation=snapshot.generation,
        input_fingerprint=render_fingerprint,
        metadata={
            "taskId": task_id,
            "runId": specialist_run_id,
            "sourceSelections": source_selections,
        },
        created_at=now,
    )
    candidate.generation = snapshot.generation + 1
    candidate.updated_at = now
    updated = services.projects.replace(
        record.project_id,
        candidate,
        snapshot.etag,
    )
    return (
        WorkGraph(
            nodes=(
                WorkNode(
                    node_id=f"compose:{timeline_id}",
                    kind="compose",
                    label="Compose final video",
                    status=WorkNodeStatus.DONE,
                    timeline_id=timeline_id,
                    task_id=task_id,
                    target_ref=f"timeline:{timeline_id}",
                    dispatch_fingerprint=compose_fingerprint,
                ),
            ),
            generation=updated.generation,
        ),
        content,
    )


def test_workflow_stage_and_event_models_are_strict_and_bounded() -> None:
    assert get_args(CreatorVideoWorkflowStage) == (
        "prepared",
        "bootstrapping",
        "planning",
        "waiting_setup",
        "waiting_approval",
        "storyboarding",
        "generating_video",
        "composing",
        "publishing",
        "succeeded",
        "failed",
        "cancelled",
    )
    event = CreatorVideoWorkflowEvent(
        sequence=0,
        cursor="prepared",
        stage="prepared",
        status="pending",
        text_result="Prepared.",
        evidence_digest="0" * 64,
        created_at=1.0,
    )
    with pytest.raises(ValidationError):
        CreatorVideoWorkflowEvent(
            sequence="0",
            cursor="prepared",
            stage="prepared",
            status="pending",
            text_result="Prepared.",
            evidence_digest="0" * 64,
            created_at=1.0,
        )
    with pytest.raises(ValidationError):
        CreatorVideoWorkflowEvent(
            sequence=0,
            cursor="prepared",
            stage="prepared",
            status="running",
            text_result="Prepared.",
            evidence_digest="0" * 64,
            created_at=1.0,
        )
    with pytest.raises(ValidationError):
        CreatorVideoWorkflowEvent(
            sequence=-1,
            cursor="invalid",
            stage="prepared",
            status="pending",
            text_result="Prepared.",
            evidence_digest="0" * 64,
            created_at=1.0,
        )
    with pytest.raises(ValidationError):
        event.text_result = "mutated"


def test_workflow_submission_rejects_nonmonotonic_and_competing_waits(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    candidate, _request = adapter._candidate(services, _submission())
    dumped = candidate.model_dump(mode="python")
    dumped["events"] = (
        candidate.events[0],
        candidate.events[0].model_copy(update={"sequence": 2}),
    )
    dumped["stage"] = "prepared"
    with pytest.raises(ValidationError, match="contiguous"):
        CreatorVideoWorkflowSubmission.model_validate(dumped)

    dumped = candidate.model_dump(mode="python")
    dumped.update(
        {
            "stage": "waiting_setup",
            "creator_session_id": "session-1",
            "conversation_id": "conversation-1",
            "goal_id": "goal-1",
            "initial_message_id": "message-1",
            "setup_request_id": "setup-1",
            "approval_request_id": "approval-1",
            "events": (
                candidate.events[0],
                CreatorVideoWorkflowEvent(
                    sequence=1,
                    cursor="waiting-setup",
                    stage="waiting_setup",
                    status="waiting_for_setup",
                    text_result="Waiting for setup.",
                    evidence_digest="0" * 64,
                    created_at=candidate.created_at,
                ),
            ),
        },
    )
    with pytest.raises(ValidationError, match="mutually exclusive"):
        CreatorVideoWorkflowSubmission.model_validate(dumped)


def test_workflow_maps_defaults_without_template_or_preauthorization(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission()

    record, request = adapter._candidate(services, submission)

    assert record.normalized_input.model_dump(mode="json") == {
        "brief": "Create a calm launch video.",
        "name": None,
        "script": None,
        "description": "",
        "scenario": "general",
        "aspect_ratio": "16:9",
        "resolution": "720P",
        "content_type": None,
        "duration_seconds": None,
        "language": "zh-CN",
    }
    assert request.client_request_id == submission.handle.submission_id
    assert request.name == derive_creator_video_project_name(
        record.normalized_input,
        submission.handle.submission_id,
    )
    assert request.initial_goal == render_creator_video_goal_v1(
        record.normalized_input,
        submission.handle.submission_id,
    )
    assert request.template_id is None
    assert request.execution_preauthorization is None
    assert record.input_digest == content_digest(
        record.normalized_input.model_dump(mode="json"),
    )
    assert record.goal_digest == content_digest(request.initial_goal)


@pytest.mark.asyncio
async def test_workflow_submit_retries_and_concurrency_create_one_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    notifications: list[str] = []
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda project_id: notifications.append(project_id) or True,
    )
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission()

    refs = await asyncio.gather(
        adapter.submit(submission),
        adapter.submit(submission),
        adapter.submit(submission),
    )
    replay = await adapter.submit(submission)

    assert refs == [replay, replay, replay]
    assert replay.executor_id == CREATOR_VIDEO_WORKFLOW_EXECUTOR_ID
    assert replay.session_id == services.project_creation.project_id(
        submission.handle.submission_id,
    )
    assert replay.run_id == submission.handle.submission_id
    assert len(services.projects.list()) == 1

    record = _workflow_record(services, submission.handle.submission_id)
    assert record.stage == "planning"
    assert record.creator_session_id is not None
    assert record.conversation_id is not None
    assert record.goal_id is not None
    assert record.initial_message_id is not None
    assert [event.sequence for event in record.events] == [0, 1, 2]
    assert [event.stage for event in record.events] == [
        "prepared",
        "bootstrapping",
        "planning",
    ]

    session = services.sessions.get_project_session(record.project_id)
    conversations = services.sessions.list_conversations(
        record.project_id,
        record.creator_session_id,
    )
    goal = services.sessions.get_goal(record.project_id, record.goal_id)
    messages = services.sessions.list_messages(
        record.project_id,
        record.creator_session_id,
    )
    bootstrap = session.metadata["projectCreate"]["runtimeBootstrap"]
    assert bootstrap["goalId"] == record.goal_id == goal.goal_id
    assert (
        bootstrap["initialMessageId"]
        == record.initial_message_id
        == messages[0].message_id
    )
    assert session.session_id == record.creator_session_id
    assert [item.conversation_id for item in conversations] == [
        record.conversation_id,
    ]
    assert len(messages) == 1
    assert goal.intent == render_creator_video_goal_v1(
        record.normalized_input,
        record.submission_id,
    )
    assert notifications
    persisted_tasks = ProjectExecutionStore(services.root).list_tasks(
        record.project_id,
    )
    assert persisted_tasks == []
    project = services.projects.read(record.project_id).project
    assert project.assets.artifact_versions_by_id == {}


@pytest.mark.asyncio
async def test_workflow_rejects_meaning_drift_for_same_submission(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    await adapter.submit(_submission())

    with pytest.raises(
        TaskStoreError,
        match="creator_video_workflow_submission_conflict",
    ):
        await adapter.submit(
            _submission(inputs={"brief": "A different video."}),
        )


@pytest.mark.asyncio
async def test_query_recovers_crash_after_project_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-crash-recovery")
    notifications: list[str] = []
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda project_id: notifications.append(project_id) or True,
    )

    def lose_workflow_update(*_args, **_kwargs):
        raise RuntimeError("injected workflow receipt loss")

    monkeypatch.setattr(adapter, "_transition_planning", lose_workflow_update)
    with pytest.raises(RuntimeError, match="workflow receipt loss"):
        await adapter.submit(submission)

    before = _workflow_record(services, submission.handle.submission_id)
    assert before.stage == "bootstrapping"
    assert notifications == []
    assert len(services.projects.list()) == 1

    recovered = CreatorVideoWorkflowTaskAdapter(lambda: services)
    lookup = await recovered.query(submission)
    record = _workflow_record(services, submission.handle.submission_id)

    assert lookup.state == "accepted"
    assert lookup.run_ref == recovered._run_ref(record)
    assert record.stage == "planning"
    assert notifications == [record.project_id]
    assert len(services.projects.list()) == 1
    assert (
        len(
            services.sessions.list_messages(
                record.project_id,
                record.creator_session_id,
            ),
        )
        == 1
    )
    persisted_tasks = ProjectExecutionStore(services.root).list_tasks(
        record.project_id,
    )
    assert persisted_tasks == []


@pytest.mark.asyncio
async def test_query_recovers_missing_adapter_receipt_without_new_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-missing-receipt")
    _candidate, request = adapter._candidate(services, submission)
    created = services.project_creation.create_with_runtime_identity(request)
    create_calls = 0

    def forbid_create(_self, _request):
        nonlocal create_calls
        create_calls += 1
        raise AssertionError("query must not create replacement work")

    monkeypatch.setattr(
        type(services.project_creation),
        "create_with_runtime_identity",
        forbid_create,
    )
    notifications: list[str] = []
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda project_id: notifications.append(project_id) or True,
    )

    lookup = await adapter.query(submission)
    record = _workflow_record(services, submission.handle.submission_id)

    assert lookup.state == "accepted"
    assert lookup.run_ref is not None
    assert lookup.run_ref.session_id == created.response.project_id
    assert record.goal_id == created.goal_id
    assert record.initial_message_id == created.initial_message_id
    assert create_calls == 0
    assert notifications == [record.project_id]


@pytest.mark.asyncio
async def test_query_absence_is_authoritative_only_without_admission(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    missing = _submission("create-video-never-submitted")

    assert (await adapter.query(missing)).state == "not_found"

    record, _request = await asyncio.to_thread(
        adapter._prepare,
        services,
        _submission("create-video-prepared-only"),
    )
    assert record.stage == "prepared"
    assert (
        await adapter.query(_submission("create-video-prepared-only"))
    ).state == "unknown"


@pytest.mark.asyncio
async def test_attach_replays_only_persisted_ordered_bootstrap_events(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-attach")
    run_ref = await adapter.submit(submission)

    events = [event async for event in adapter.attach(submission)]
    resumed = _submission(
        "create-video-attach",
        executor_sequence=0,
    )
    replay = [event async for event in adapter.attach(resumed)]

    assert all(event.run_ref == run_ref for event in events)
    assert [event.sequence for event in events] == [0, 1, 2]
    assert [event.status for event in events] == [
        "pending",
        "running",
        "running",
    ]
    assert [event.sequence for event in replay] == [1, 2]
    assert [event.text_result for event in replay] == [
        "Creator is creating the video project.",
        "Creator is planning the video.",
    ]


@pytest.mark.asyncio
async def test_observer_applies_precedence_and_recovers_to_planning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-observation-precedence")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "_automatic_regeneration_enabled",
        lambda: False,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record)
    executions = ProjectExecutionStore(services.root)
    compose_task = executions.create_task(
        TaskRecord(
            task_id="compose-task-1",
            project_id=record.project_id,
            round_id=run.round_id,
            kind=TaskKind.COMPOSE,
            request_fingerprint="compose-fingerprint",
        ),
    )
    current_graph = [
        _graph(
            _node("storyboard", WorkNodeStatus.READY),
            _node("video", WorkNodeStatus.READY),
            _node(
                "compose",
                WorkNodeStatus.RUNNING,
                task_id=compose_task.task_id,
            ),
        ),
    ]
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: current_graph[0],
    )

    await adapter.query(submission)
    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == "composing"
    assert observed.events[-1].setup_requirement_id == "storyboard-image"

    executions.transition_task(
        record.project_id,
        compose_task.task_id,
        expected_status="QUEUED",
        status="RUNNING",
    )
    executions.transition_task(
        record.project_id,
        compose_task.task_id,
        expected_status="RUNNING",
        status="SUCCEEDED",
    )
    current_graph[0] = _graph(
        _node("storyboard", WorkNodeStatus.READY),
        _node("video", WorkNodeStatus.READY),
    )
    await adapter.query(submission)
    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == "generating_video"
    assert observed.events[-1].setup_requirement_id == "storyboard-image"

    previous_sequence = observed.events[-1].sequence
    current_graph[0] = _graph(_node("video", WorkNodeStatus.READY))
    await adapter.query(submission)
    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == "generating_video"
    assert observed.events[-1].setup_requirement_id == "shot-video"
    setup_events = [
        event
        async for event in adapter.attach(
            _submission(
                "create-video-observation-precedence",
                executor_sequence=previous_sequence,
            ),
        )
    ]
    assert len(setup_events) == 1
    assert setup_events[0].status == "waiting_for_setup"
    assert setup_events[0].setup_need is not None
    assert setup_events[0].setup_need.model_dump(mode="json") == {
        "requirement_id": "shot-video",
        "reason_code": "creator_video_model_missing",
        "reason": "Configure and enable the Creator video generation model.",
    }

    current_graph[0] = _graph(_node("storyboard", WorkNodeStatus.READY))
    await adapter.query(submission)
    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == "storyboarding"
    assert observed.events[-1].setup_requirement_id == "storyboard-image"

    current_graph[0] = _graph(_node("storyboard", WorkNodeStatus.FAILED))
    await adapter.query(submission)
    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == "planning"
    assert [event.sequence for event in observed.events] == list(
        range(len(observed.events)),
    )
    assert [event.stage for event in observed.events[-5:]] == [
        "composing",
        "generating_video",
        "generating_video",
        "storyboarding",
        "planning",
    ]
    assert all(len(event.evidence_digest) == 64 for event in observed.events)


@pytest.mark.asyncio
async def test_deferred_setup_check_precedes_pending_correlated_authorization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-observation-approval")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record)
    authorization = ProjectExecutionStore(
        services.root,
    ).create_execution_authorization(
        ExecutionAuthorizationRecord(
            authorization_id="authorization-1",
            project_id=record.project_id,
            round_id=run.round_id,
            run_id=run.run_id,
            execution_request_id="execution-request-1",
            operation="generate_video",
            target_scope=["video:final"],
            authorization_token="opaque-token",
            summary="Generate the final video.",
        ),
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(
            _node("video", WorkNodeStatus.READY),
        ),
    )

    await adapter.query(submission)
    setup = _workflow_record(services, record.submission_id)

    assert setup.stage == "generating_video"
    assert setup.approval_request_id is None
    assert setup.events[-1].setup_requirement_id == "shot-video"
    assert setup.correlated_run_ids == (run.run_id,)
    stored_authorization = ProjectExecutionStore(
        services.root,
    ).get_execution_authorization(
        record.project_id,
        authorization.authorization_id,
    )
    assert stored_authorization.status is ExecutionAuthorizationStatus.PENDING

    await adapter.query(submission)
    replayed = _workflow_record(services, record.submission_id)
    assert replayed.events[-1] == setup.events[-1]

    resumed = submission.model_copy(
        update={
            "handle": submission.handle.model_copy(
                update={"executor_sequence": setup.events[-1].sequence},
            ),
        },
    )
    await adapter.query(resumed)
    observed = _workflow_record(services, record.submission_id)

    assert observed.stage == "waiting_approval"
    assert observed.approval_request_id == authorization.authorization_id
    assert observed.events[-1].status == "waiting_for_approval"


@pytest.mark.asyncio
async def test_setup_expires_stale_authorization_before_approval_presentation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-stale-setup-approval")
    notifications = []
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda project_id: notifications.append(project_id) or True,
    )
    node = _node("storyboard", WorkNodeStatus.READY)
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(node),
    )
    active_identity = [("openai", "gpt-image-2")]
    monkeypatch.setattr(
        pawapp_video_workflow,
        "execution_provider_model",
        lambda _spec, _arguments: active_identity[0],
    )

    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record)
    stale = _authorization(
        services,
        record,
        run,
        authorization_id="authorization-before-setup",
        operation="image_generation",
        target_scope=[node.target_ref],
        requested_provider="openai",
        requested_model="gpt-image-2",
    )

    await adapter.query(submission)
    setup = _workflow_record(services, record.submission_id)
    assert setup.events[-1].setup_requirement_id == "storyboard-image"
    assert ProjectExecutionStore(services.root).get_execution_authorization(
        record.project_id,
        stale.authorization_id,
    ).status is ExecutionAuthorizationStatus.PENDING
    notifications_before_expiration = len(notifications)

    active_identity[0] = ("dashscope", "wan2.2-t2i-flash")
    resumed = submission.model_copy(
        update={
            "handle": submission.handle.model_copy(
                update={"executor_sequence": setup.events[-1].sequence},
            ),
        },
    )
    await adapter.query(resumed)
    expired = ProjectExecutionStore(
        services.root,
    ).get_execution_authorization(
        record.project_id,
        stale.authorization_id,
    )
    assert expired.status is ExecutionAuthorizationStatus.EXPIRED
    assert expired.metadata == {
        "expiredBy": "pawapp_video_workflow",
        "reason": "execution_configuration_changed",
    }
    assert _workflow_record(
        services,
        record.submission_id,
    ).approval_request_id is None

    fresh = _authorization(
        services,
        record,
        run,
        authorization_id="authorization-after-setup",
        operation="image_generation",
        target_scope=[node.target_ref],
        requested_provider="dashscope",
        requested_model="wan2.2-t2i-flash",
    )
    await adapter.query(resumed)
    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == "waiting_approval"
    assert observed.approval_request_id == fresh.authorization_id
    assert len(notifications) == notifications_before_expiration + 1


@pytest.mark.asyncio
async def test_approval_prompt_is_bounded_and_approval_replays_after_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-approval-command")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(
            _node("video", WorkNodeStatus.READY),
        ),
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record)
    authorization = _authorization(services, record, run)
    submission = await _query_after_deferred_setup_check(
        adapter,
        services,
        submission,
    )

    events = [event async for event in adapter.attach(submission)]
    approval = events[-1]
    request = approval.detail["input_request"]

    assert approval.status == "waiting_for_approval"
    assert request == {
        "request_id": request["request_id"],
        "title": "Creator generation approval",
        "questions": [
            {
                "question": "Run this Creator generation operation once?",
                "description": (
                    "Operation: Generate a video shot. Target: current "
                    "storyboard shot. Provider: video-provider. Model: "
                    "video-model. Candidate count: 2. Duration: 5 seconds. "
                    "Resolution: 1080P. Aspect ratio: 9:16. Mode: fast. "
                    "Audio: enabled."
                ),
                "multi_select": False,
                "options": [
                    {
                        "label": "Approve once",
                        "description": "Approve only this immutable request.",
                    },
                    {
                        "label": "Do not run",
                        "description": (
                            "Reject this request without starting it."
                        ),
                    },
                ],
            },
        ],
    }
    assert request["request_id"] != authorization.authorization_id
    exposed = str(request)
    for hidden in (
        authorization.authorization_id,
        authorization.authorization_token,
        authorization.execution_request_id,
        authorization.target_scope[0],
        authorization.summary,
        "hidden raw generation prompt",
    ):
        assert hidden not in exposed

    command = _answer_command(
        submission,
        request["request_id"],
        "Approve once",
    )
    assert (await adapter.command(submission, command)).state == "accepted"
    stored = ProjectExecutionStore(
        services.root,
    ).get_execution_authorization(
        record.project_id,
        authorization.authorization_id,
    )
    assert stored.status is ExecutionAuthorizationStatus.APPROVED
    assert stored.decision == {
        "provider": "video-provider",
        "model": "video-model",
        "maxCost": 0,
        "maxCandidates": 2,
    }

    await adapter.query(submission)
    assert _workflow_record(services, record.submission_id).stage == (
        "generating_video"
    )
    command_status = await adapter.query_command(submission, command)
    assert command_status.state == "accepted"


@pytest.mark.asyncio
async def test_approval_rejects_conflicting_and_expired_answers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(
            _node("video", WorkNodeStatus.READY),
        ),
    )

    rejected_submission = _submission("create-video-rejected-approval")
    await adapter.submit(rejected_submission)
    rejected_record = _workflow_record(
        services,
        rejected_submission.handle.submission_id,
    )
    rejected_run = _agent_run(services, rejected_record)
    rejected_authorization = _authorization(
        services,
        rejected_record,
        rejected_run,
    )
    rejected_submission = await _query_after_deferred_setup_check(
        adapter,
        services,
        rejected_submission,
    )
    rejected_events = [
        event async for event in adapter.attach(rejected_submission)
    ]
    request_id = rejected_events[-1].detail["input_request"]["request_id"]
    reject = _answer_command(
        rejected_submission,
        request_id,
        "Do not run",
    )

    rejection = await adapter.command(rejected_submission, reject)
    assert rejection.state == "accepted"
    approve = _answer_command(
        rejected_submission,
        request_id,
        "Approve once",
        command_id="answer-conflict",
    )
    conflict = await adapter.command(rejected_submission, approve)
    assert conflict.model_dump(mode="json") == {
        "state": "rejected",
        "reason": "approval_already_decided",
    }
    assert (
        ProjectExecutionStore(services.root)
        .get_execution_authorization(
            rejected_record.project_id,
            rejected_authorization.authorization_id,
        )
        .status
        is ExecutionAuthorizationStatus.REJECTED
    )

    expired_submission = _submission(
        "create-video-expired-approval",
        task_id="host-create-video-task-expired",
    )
    await adapter.submit(expired_submission)
    expired_record = _workflow_record(
        services,
        expired_submission.handle.submission_id,
    )
    expired_run = _agent_run(
        services,
        expired_record,
        run_id="agent-run-expired",
    )
    _authorization(
        services,
        expired_record,
        expired_run,
        expires_at=utc_now() - timedelta(seconds=1),
    )
    expired_submission = await _query_after_deferred_setup_check(
        adapter,
        services,
        expired_submission,
    )
    expired_events = [
        event async for event in adapter.attach(expired_submission)
    ]
    expired = await adapter.command(
        expired_submission,
        _answer_command(
            expired_submission,
            expired_events[-1].detail["input_request"]["request_id"],
            "Approve once",
        ),
    )
    assert expired.model_dump(mode="json") == {
        "state": "rejected",
        "reason": "approval_expired",
    }


@pytest.mark.asyncio
async def test_sequential_approvals_get_distinct_host_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-sequential-approvals")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(
            _node("video", WorkNodeStatus.READY),
        ),
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record)
    first = _authorization(services, record, run, "authorization-first")
    submission = await _query_after_deferred_setup_check(
        adapter,
        services,
        submission,
    )
    first_event = [event async for event in adapter.attach(submission)][-1]
    first_request_id = first_event.detail["input_request"]["request_id"]
    await adapter.command(
        submission,
        _answer_command(submission, first_request_id, "Approve once"),
    )
    await adapter.query(submission)

    second = _authorization(services, record, run, "authorization-second")
    previous_sequence = (
        _workflow_record(
            services,
            record.submission_id,
        )
        .events[-1]
        .sequence
    )
    await adapter.query(submission)
    second_events = [
        event
        async for event in adapter.attach(
            _submission(
                submission.handle.submission_id,
                executor_sequence=previous_sequence,
            ),
        )
    ]
    second_request_id = second_events[-1].detail["input_request"]["request_id"]

    assert second_request_id != first_request_id
    assert second_request_id != second.authorization_id
    second_command = _answer_command(
        submission,
        second_request_id,
        "Approve once",
        command_id="answer-second",
    )
    second_result = await adapter.command(submission, second_command)
    assert second_result.state == "accepted"
    store = ProjectExecutionStore(services.root)
    assert (
        store.get_execution_authorization(
            record.project_id,
            first.authorization_id,
        ).status
        is ExecutionAuthorizationStatus.APPROVED
    )
    assert (
        store.get_execution_authorization(
            record.project_id,
            second.authorization_id,
        ).status
        is ExecutionAuthorizationStatus.APPROVED
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_status", "run_error", "node", "expected_code"),
    [
        (
            AgentRunStatus.FAILED,
            {"code": "MODEL_FAILED"},
            _node("storyboard", WorkNodeStatus.FAILED),
            None,
        ),
        (
            AgentRunStatus.FAILED,
            {"code": "MODEL_FAILED"},
            None,
            "creator_runtime_failed",
        ),
        (AgentRunStatus.SUCCEEDED, None, None, "no_actionable_work"),
    ],
)
async def test_observer_only_fails_after_recoverable_work_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    run_status: AgentRunStatus,
    run_error: dict | None,
    node: WorkNode | None,
    expected_code: str | None,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission_id = f"create-video-terminal-{run_status.value}-{bool(node)}"
    submission = _submission(submission_id)
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "_automatic_regeneration_enabled",
        lambda: False,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    _agent_run(
        services,
        record,
        status=run_status,
        error=run_error,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(*(() if node is None else (node,))),
    )

    await adapter.query(submission)
    observed = _workflow_record(services, record.submission_id)

    if expected_code is None:
        assert observed.stage == "planning"
        assert observed.failure_code is None
    else:
        assert observed.stage == "failed"
        assert observed.failure_code == expected_code
        terminal_events = tuple(observed.events)
        await adapter.query(submission)
        replayed = _workflow_record(services, record.submission_id)
        assert replayed.events == terminal_events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node", "expected_stage"),
    [
        (_node("compose", WorkNodeStatus.READY), "composing"),
        (_node("script", WorkNodeStatus.READY), "planning"),
        (_node("compose", WorkNodeStatus.DONE), "failed"),
    ],
)
async def test_observer_keeps_machine_work_recoverable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    node: WorkNode,
    expected_stage: str,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission(
        f"create-video-machine-{node.kind}-{node.status.value}",
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(node),
    )

    await adapter.query(submission)

    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == expected_stage
    assert observed.failure_code == (
        "no_actionable_work" if expected_stage == "failed" else None
    )


@pytest.mark.asyncio
async def test_observer_keeps_unmapped_active_task_recoverable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-unmapped-active-task")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    ProjectExecutionStore(services.root).create_task(
        TaskRecord(
            task_id="source-intelligence-task",
            project_id=record.project_id,
            round_id=run.round_id,
            kind=TaskKind.SOURCE_INTELLIGENCE,
            request_fingerprint="source-intelligence-fingerprint",
        ),
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(),
    )

    await adapter.query(submission)

    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == "planning"
    assert observed.failure_code is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "goal_status", "session_status", "expected_stage"),
    [
        ("USER_CANCELLED", "CANCELLED", "CANCELLED", "cancelled"),
        ("SUPERSEDED", "RESUME_REQUIRED", "RESUMING", "planning"),
        ("SHUTDOWN", "CANCELLED", "CANCELLED", "planning"),
        ("ORPHANED_BY_RESTART", "CANCELLED", "CANCELLED", "planning"),
        ("DUPLICATE_ADMISSION", "CANCELLED", "CANCELLED", "planning"),
    ],
)
async def test_observer_distinguishes_cancellation_from_supersession(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error_code: str,
    goal_status: str,
    session_status: str,
    expected_stage: str,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission(f"create-video-cancel-{error_code.lower()}")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    _agent_run(
        services,
        record,
        status=AgentRunStatus.CANCELLED,
        error={"code": error_code},
    )
    services.sessions.set_goal_status(
        record.project_id,
        record.goal_id,
        goal_status,
    )
    services.sessions.set_session_status(
        record.project_id,
        record.creator_session_id,
        session_status,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(),
    )

    await adapter.query(submission)

    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == expected_stage


@pytest.mark.asyncio
async def test_observer_follows_resume_chain_and_ignores_unrelated_goal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-causal-chain")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    first_run = _agent_run(
        services,
        record,
        run_id="agent-run-initial",
        status=AgentRunStatus.SUCCEEDED,
    )
    services.sessions.set_goal_status(
        record.project_id,
        record.goal_id,
        "COMPLETED",
    )
    resume = services.sessions.append_message(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        role="user",
        content_parts=[{"type": "text", "text": "Continue production."}],
        source="yolo_auto_resume",
        metadata={"resumeAfterRunId": first_run.run_id},
    ).message
    successor_goal = services.sessions.create_goal(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        root_message_seq=resume.message_seq,
        intent="Continue production.",
        goal_id="goal-successor",
    )
    successor_run = _agent_run(
        services,
        record,
        run_id="agent-run-successor",
        goal_id=successor_goal.goal_id,
        message_id=resume.message_id,
        message_seq=resume.message_seq,
    )
    unrelated = services.sessions.append_message(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        role="user",
        content_parts=[{"type": "text", "text": "Unrelated edit."}],
        source="frontend_manual_edit",
    ).message
    unrelated_goal = services.sessions.create_goal(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        root_message_seq=unrelated.message_seq,
        intent="Unrelated edit.",
        goal_id="goal-unrelated",
    )
    _agent_run(
        services,
        record,
        run_id="agent-run-unrelated",
        status=AgentRunStatus.CANCELLED,
        error={"code": "USER_CANCELLED"},
        goal_id=unrelated_goal.goal_id,
        message_id=unrelated.message_id,
        message_seq=unrelated.message_seq,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(),
    )

    await adapter.query(submission)
    observed = _workflow_record(services, record.submission_id)

    assert observed.stage == "planning"
    assert observed.correlated_goal_ids == (
        record.goal_id,
        successor_goal.goal_id,
    )
    assert observed.correlated_run_ids == (
        first_run.run_id,
        successor_run.run_id,
    )
    assert "agent-run-unrelated" not in observed.correlated_run_ids


@pytest.mark.asyncio
async def test_observer_follows_linked_runtime_notification_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-runtime-notification-chain")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    first_run = _agent_run(
        services,
        record,
        run_id="agent-run-initial",
        status=AgentRunStatus.SUCCEEDED,
    )
    services.sessions.set_goal_status(
        record.project_id,
        record.goal_id,
        "COMPLETED",
    )
    snapshot = services.projects.read(record.project_id)
    executions = ProjectExecutionStore(services.root)
    specialist = executions.create_specialist_run(
        SpecialistRunRecord(
            run_id="specialist-run-linked",
            project_id=record.project_id,
            round_id=first_run.round_id,
            role=SpecialistRole.SOURCE_INTELLIGENCE,
            target_refs=["project:source"],
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            related_run_id=first_run.run_id,
        ),
    )
    specialist_notification = services.sessions.append_message(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        role="user",
        content_parts=[{"type": "text", "text": "Specialist completed."}],
        source=pawapp_video_workflow.NOTIFICATION_SOURCE,
        metadata={"specialistRunId": specialist.run_id},
    ).message
    specialist_goal = services.sessions.create_goal(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        root_message_seq=specialist_notification.message_seq,
        intent="Continue after specialist completion.",
        goal_id="goal-after-specialist",
    )
    second_run = _agent_run(
        services,
        record,
        run_id="agent-run-after-specialist",
        status=AgentRunStatus.SUCCEEDED,
        goal_id=specialist_goal.goal_id,
        message_id=specialist_notification.message_id,
        message_seq=specialist_notification.message_seq,
    )
    task = executions.create_task(
        TaskRecord(
            task_id="script-task-linked",
            project_id=record.project_id,
            round_id=second_run.round_id,
            kind=TaskKind.SCRIPT_DRAFT,
            request_fingerprint="script-task-fingerprint",
        ),
    )
    node = _node("script", WorkNodeStatus.RUNNING, task_id=task.task_id)
    scheduler_notification = services.sessions.append_message(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        role="user",
        content_parts=[{"type": "text", "text": "Script task progressed."}],
        source=pawapp_video_workflow.NOTIFICATION_SOURCE,
        metadata={"nodeId": node.node_id},
    ).message
    scheduler_goal = services.sessions.create_goal(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        root_message_seq=scheduler_notification.message_seq,
        intent="Continue after script progress.",
        goal_id="goal-after-scheduler",
    )
    third_run = _agent_run(
        services,
        record,
        run_id="agent-run-after-scheduler",
        goal_id=scheduler_goal.goal_id,
        message_id=scheduler_notification.message_id,
        message_seq=scheduler_notification.message_seq,
    )
    unrelated_notification = services.sessions.append_message(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        role="user",
        content_parts=[{"type": "text", "text": "Unrelated notification."}],
        source=pawapp_video_workflow.NOTIFICATION_SOURCE,
        metadata={"nodeId": "unrelated-node"},
    ).message
    unrelated_goal = services.sessions.create_goal(
        record.project_id,
        record.creator_session_id,
        record.conversation_id,
        root_message_seq=unrelated_notification.message_seq,
        intent="Unrelated runtime activity.",
        goal_id="goal-unrelated-notification",
    )
    _agent_run(
        services,
        record,
        run_id="agent-run-unrelated-notification",
        status=AgentRunStatus.CANCELLED,
        error={"code": "USER_CANCELLED"},
        goal_id=unrelated_goal.goal_id,
        message_id=unrelated_notification.message_id,
        message_seq=unrelated_notification.message_seq,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(node),
    )

    await adapter.query(submission)

    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == "planning"
    assert set(observed.correlated_goal_ids) == {
        record.goal_id,
        specialist_goal.goal_id,
        scheduler_goal.goal_id,
    }
    assert observed.correlated_run_ids == (
        first_run.run_id,
        second_run.run_id,
        third_run.run_id,
        specialist.run_id,
    )
    assert (
        "agent-run-unrelated-notification" not in observed.correlated_run_ids
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("recoverable", "expected_stage"),
    [(False, "failed"), (True, "planning")],
)
async def test_multiple_live_timelines_require_explicit_repair_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    recoverable: bool,
    expected_stage: str,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission(
        f"create-video-multiple-timelines-{recoverable}",
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    snapshot = services.projects.read(record.project_id)
    candidate = snapshot.project.model_copy(deep=True)
    candidate.timelines.items["timeline:second"] = Timeline(
        timeline_id="timeline:second",
    )
    candidate.timelines.order.append("timeline:second")
    candidate.generation = snapshot.generation + 1
    candidate.updated_at = utc_now()
    services.projects.replace(record.project_id, candidate, snapshot.etag)
    if recoverable:
        services.sessions.set_session_status(
            record.project_id,
            record.creator_session_id,
            "PENDING_REVIEW",
        )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(
            _node("compose", WorkNodeStatus.READY),
        ),
    )

    await adapter.query(submission)

    observed = _workflow_record(services, record.submission_id)
    assert observed.stage == expected_stage
    if recoverable:
        assert observed.failure_code is None
        return
    assert observed.failure_code == "multiple_live_timelines"
    event = [event async for event in adapter.attach(submission)][-1]
    assert "leave one live timeline" in event.text_result
    assert event.detail["project_ref"]["project_id"] == record.project_id
    assert "timeline:second" not in event.text_result


@pytest.mark.asyncio
async def test_publication_supersedes_intent_before_host_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path / "creator")
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-prepublish-supersession")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    run_ref = await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    first_graph, _first_content = _install_final_video(
        services,
        record,
        run,
        "prepublish-v1",
    )
    current_graph = [first_graph]
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: current_graph[0],
    )
    await adapter.query(submission)
    first_intent = _workflow_record(services, record.submission_id)

    second_graph, expected_content = _install_final_video(
        services,
        record,
        run,
        "prepublish-v2",
    )
    current_graph[0] = second_graph
    await adapter.query(submission)

    superseded = _workflow_record(services, record.submission_id)
    assert superseded.stage == "publishing"
    assert superseded.publication is not None
    assert (
        superseded.publication.intent_id != first_intent.publication.intent_id
    )
    assert len(superseded.superseded_publications) == 1
    old_intent = superseded.superseded_publications[0]
    assert old_intent.state == "superseded"
    assert old_intent.artifact_ref is None
    assert old_intent.published_at is None

    accepted = _accepted_submission(
        submission,
        run_ref,
        executor_sequence=first_intent.events[-1].sequence,
    )
    artifacts = await ArtifactStore.open(tmp_path / "host-artifacts")
    publish_event = [event async for event in adapter.attach(accepted)][-1]
    await adapter.materialize_event(accepted, publish_event, artifacts)

    succeeded = _workflow_record(services, record.submission_id)
    assert succeeded.stage == "succeeded"
    assert succeeded.publication is not None
    assert succeeded.publication.artifact_ref is not None
    assert succeeded.publication.artifact_ref.version == 1
    _ref, published_content = await artifacts.read(
        submission.handle.scope,
        succeeded.publication.artifact_ref.artifact_id,
        succeeded.publication.artifact_ref.version,
    )
    assert published_content == expected_content


@pytest.mark.asyncio
async def test_query_retries_revalidation_after_temporary_source_gap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path / "creator")
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-revalidate-source-gap")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    run_ref = await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    final_graph, _content = _install_final_video(services, record, run, "gap")
    current_graph = [final_graph]
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: current_graph[0],
    )
    await adapter.query(submission)
    intent = _workflow_record(services, record.submission_id)
    accepted = _accepted_submission(submission, run_ref)
    artifacts = await ArtifactStore.open(tmp_path / "host-artifacts")
    source, content = adapter._read_publication_artifact(services, intent)
    artifact_ref = await artifacts.publish(accepted, source, content)
    published = adapter._record_published_artifact(
        services,
        intent,
        artifact_ref,
    )
    source_receipt = published.source_receipt
    assert source_receipt is not None
    current_graph[0] = WorkGraph(
        nodes=(
            WorkNode(
                node_id="compose-node-gap-running",
                kind="compose",
                label="Compose final video",
                status=WorkNodeStatus.RUNNING,
                timeline_id=source_receipt.timeline_id,
                task_id=source_receipt.producer_task_id,
                target_ref=f"timeline:{source_receipt.timeline_id}",
                dispatch_fingerprint=source_receipt.compose_fingerprint,
            ),
        ),
        generation=final_graph.generation,
    )

    await adapter.query(submission)

    waiting = _workflow_record(services, record.submission_id)
    assert waiting.stage == "publishing"
    assert waiting.events == published.events

    current_graph[0] = final_graph
    await adapter.query(submission)

    succeeded = _workflow_record(services, record.submission_id)
    assert succeeded.stage == "succeeded"
    resumed = _accepted_submission(
        submission,
        run_ref,
        executor_sequence=published.events[-1].sequence,
    )
    terminal = [event async for event in adapter.attach(resumed)]
    assert len(terminal) == 1
    materialized = await adapter.materialize_event(
        resumed,
        terminal[0],
        artifacts,
    )
    assert materialized.status == "succeeded"
    assert materialized.detail["artifact_ref"] == artifact_ref.model_dump(
        mode="json",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("stale", "final_source_invalid"),
        ("wrong_media", "final_source_invalid"),
        ("wrong_producer", "final_source_untrusted"),
        ("wrong_fingerprint", "final_source_untrusted"),
        ("oversized", "publication_source_mismatch"),
        ("corrupt", "publication_source_unavailable"),
    ],
)
async def test_publication_rejects_invalid_or_untrusted_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    services = _services(tmp_path / "creator")
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission(f"create-video-invalid-source-{mutation}")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    run_ref = await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    graph, _content = _install_final_video(
        services,
        record,
        run,
        f"invalid-{mutation}",
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: graph,
    )

    if mutation != "corrupt":
        snapshot = services.projects.read(record.project_id)
        candidate = snapshot.project.model_copy(deep=True)
        timeline_id = narrative_timeline_ids(candidate)[0]
        slot_id = f"timeline:{timeline_id}:render"
        slot = candidate.assets.artifact_slots_by_id[slot_id]
        version = candidate.assets.artifact_versions_by_id[
            slot.selected_version_id
        ]
        indexed = candidate.assets.files_by_id[version.file_id]
        if mutation == "stale":
            version.stale = True
        elif mutation == "wrong_media":
            indexed.media_type = "image/png"
        elif mutation == "wrong_producer":
            version.metadata["taskId"] = "compose-task-other"
        elif mutation == "wrong_fingerprint":
            version.input_fingerprint = "compose-fingerprint-other"
        elif mutation == "oversized":
            indexed.size_bytes = MAX_ARTIFACT_BYTES + 1
        candidate.generation = snapshot.generation + 1
        candidate.updated_at = utc_now()
        services.projects.replace(record.project_id, candidate, snapshot.etag)

    await adapter.query(submission)
    observed = _workflow_record(services, record.submission_id)
    if mutation == "corrupt":
        assert observed.source_receipt is not None
        artifact_path = (
            services.projects.project_root(
                record.project_id,
            )
            / observed.source_receipt.relative_uri
        )
        artifact_path.write_bytes(b"corrupt")
    if observed.stage == "publishing":
        accepted = _accepted_submission(submission, run_ref)
        artifacts = await ArtifactStore.open(tmp_path / "host-artifacts")
        event = [event async for event in adapter.attach(accepted)][-1]
        await adapter.materialize_event(accepted, event, artifacts)
        observed = _workflow_record(services, record.submission_id)

    assert observed.stage == "failed"
    assert observed.failure_code == expected_code


@pytest.mark.asyncio
async def test_host_adapter_commits_publication_and_terminal_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path / "creator")
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    seed = _submission("unused-host-seed")
    task_store = await TaskStore.open(tmp_path / "host" / "tasks.sqlite3")
    submission = await task_store.create(
        seed.handle.scope,
        seed.action,
        request_id="host-create-video-request",
        inputs=seed.inputs,
        origin=seed.handle.origin,
    )
    assert await task_store.begin_submission(
        submission.handle.scope,
        submission.handle.task_id,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    run_ref = await adapter.submit(submission)
    submission = await task_store.record_accepted(
        submission.handle.scope,
        submission.handle.task_id,
        run_ref,
    )
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    graph, expected_content = _install_final_video(
        services,
        record,
        run,
        "host-runtime",
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: graph,
    )
    await adapter.query(submission)
    artifacts = await ArtifactStore.open(tmp_path / "host" / "artifacts")
    ready = _ReadyAdapter(adapter, artifacts, None)

    async for event in ready.attach(submission):
        submission = await task_store.apply_event(
            submission.handle.scope,
            submission.handle.task_id,
            event,
        )

    stored = await task_store.get(
        submission.handle.scope,
        submission.handle.task_id,
    )
    workflow = _workflow_record(services, submission.handle.submission_id)
    assert stored.handle.status == "succeeded"
    assert stored.handle.executor_sequence == workflow.events[-1].sequence
    assert stored.handle.replay_cursor == workflow.events[-1].cursor
    assert stored.handle.text_result == (
        "Creator finished and published the video."
    )
    assert stored.handle.project_ref.project_id == record.project_id
    assert stored.handle.output_refs == (workflow.publication.artifact_ref,)
    artifact_ref, content = await artifacts.read(
        submission.handle.scope,
        stored.handle.output_refs[0].artifact_id,
        stored.handle.output_refs[0].version,
    )
    assert artifact_ref == stored.handle.output_refs[0]
    assert content == expected_content


@pytest.mark.asyncio
async def test_publication_replays_host_write_and_emits_one_terminal_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path / "creator")
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-publish")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    run_ref = await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    graph, expected_content = _install_final_video(
        services,
        record,
        run,
        "v1",
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: graph,
    )

    await adapter.query(submission)
    publishing = _workflow_record(services, record.submission_id)
    assert publishing.stage == "publishing"
    assert publishing.publication is not None
    assert publishing.publication.state == "intent"
    accepted = _accepted_submission(submission, run_ref)
    artifacts = await ArtifactStore.open(tmp_path / "host-artifacts")
    source, content = adapter._read_publication_artifact(
        services,
        publishing,
    )
    prepublished = await artifacts.publish(accepted, source, content)

    publish_event = [event async for event in adapter.attach(accepted)][-1]
    assert publish_event.status == "running"
    assert publish_event.text_result == (
        "Creator is publishing the final video."
    )
    assert "artifact_ref" not in publish_event.detail
    await adapter.materialize_event(accepted, publish_event, artifacts)

    succeeded = _workflow_record(services, record.submission_id)
    assert succeeded.stage == "succeeded"
    assert succeeded.publication is not None
    assert succeeded.publication.artifact_ref == prepublished
    assert succeeded.publication.validated_project_generation is not None
    assert succeeded.superseded_publications == ()

    resumed = _accepted_submission(
        submission,
        run_ref,
        executor_sequence=publish_event.sequence,
    )
    terminal_events = [event async for event in adapter.attach(resumed)]
    assert len(terminal_events) == 1
    terminal = await adapter.materialize_event(
        resumed,
        terminal_events[0],
        artifacts,
    )
    artifact_payload = terminal.detail["artifact_ref"]
    assert terminal.status == "succeeded"
    assert terminal.text_result == "Creator finished and published the video."
    assert terminal.detail["project_ref"]["project_id"] == record.project_id
    assert artifact_payload == prepublished.model_dump(mode="json")
    artifact_ref, published_content = await artifacts.read(
        submission.handle.scope,
        prepublished.artifact_id,
        prepublished.version,
    )
    assert artifact_ref == prepublished
    assert published_content == expected_content


@pytest.mark.asyncio
async def test_publication_supersedes_when_canonical_source_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path / "creator")
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-publication-supersession")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    run_ref = await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    run = _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    first_graph, _first_content = _install_final_video(
        services,
        record,
        run,
        "v1",
    )
    current_graph = [first_graph]
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: current_graph[0],
    )
    await adapter.query(submission)
    first_intent = _workflow_record(services, record.submission_id)
    accepted = _accepted_submission(submission, run_ref)
    artifacts = await ArtifactStore.open(tmp_path / "host-artifacts")
    source, content = adapter._read_publication_artifact(
        services,
        first_intent,
    )
    first_ref = await artifacts.publish(accepted, source, content)
    published = adapter._record_published_artifact(
        services,
        first_intent,
        first_ref,
    )

    second_graph, expected_content = _install_final_video(
        services,
        record,
        run,
        "v2",
    )
    current_graph[0] = second_graph
    superseded = adapter._finalize_published_artifact(services, published)
    assert superseded.stage == "publishing"
    assert superseded.publication is not None
    assert superseded.publication.state == "intent"
    assert (
        superseded.publication.intent_id != first_intent.publication.intent_id
    )
    assert len(superseded.superseded_publications) == 1
    assert superseded.superseded_publications[0].artifact_ref == first_ref

    replay = _accepted_submission(
        submission,
        run_ref,
        executor_sequence=superseded.events[-1].sequence - 1,
    )
    publish_event = [event async for event in adapter.attach(replay)][-1]
    await adapter.materialize_event(replay, publish_event, artifacts)
    succeeded = _workflow_record(services, record.submission_id)
    assert succeeded.stage == "succeeded"
    assert succeeded.publication is not None
    second_ref = succeeded.publication.artifact_ref
    assert second_ref is not None
    assert second_ref.artifact_id == first_ref.artifact_id
    assert second_ref.version == first_ref.version + 1
    _ref, published_content = await artifacts.read(
        submission.handle.scope,
        second_ref.artifact_id,
        second_ref.version,
    )
    assert published_content == expected_content


@pytest.mark.asyncio
async def test_cancellation_stops_only_correlated_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    submission = _submission("create-video-correlated-cancellation")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: _graph(),
    )
    runtime_cancellations: list[tuple[str, tuple[str, ...]]] = []

    async def cancel_runtime(
        project_id: str,
        *,
        agent_run_ids: tuple[str, ...],
        specialist_run_ids: tuple[str, ...],
    ) -> bool:
        assert agent_run_ids == specialist_run_ids
        runtime_cancellations.append((project_id, agent_run_ids))
        return True

    monkeypatch.setattr(
        pawapp_video_workflow,
        "cancel_correlated_creator_agent_runtime",
        cancel_runtime,
    )
    await adapter.submit(submission)
    record = _workflow_record(services, submission.handle.submission_id)
    project_before = services.projects.read(record.project_id)
    agent_run = _agent_run(services, record)
    executions = ProjectExecutionStore(services.root)

    correlated_run_id = "specialist-correlated"
    unrelated_run_id = "specialist-unrelated"
    for run_id, round_id, related_run_id in (
        (correlated_run_id, agent_run.round_id, agent_run.run_id),
        (unrelated_run_id, "round-unrelated", None),
    ):
        executions.create_specialist_run(
            SpecialistRunRecord(
                run_id=run_id,
                project_id=record.project_id,
                round_id=round_id,
                role=SpecialistRole.VISUAL_DEVELOPMENT,
                target_refs=[f"element:{run_id}"],
                input_generation=project_before.generation,
                input_etag=project_before.etag,
                related_run_id=related_run_id,
            ),
        )
        executions.transition_specialist_run(
            record.project_id,
            run_id,
            expected_status=SpecialistRunStatus.QUEUED,
            status=SpecialistRunStatus.RUNNING_MODEL,
        )
        task_id = f"task-{run_id}"
        executions.create_task(
            TaskRecord(
                task_id=task_id,
                project_id=record.project_id,
                round_id=round_id,
                run_id=run_id,
                kind=TaskKind.IMAGE_GENERATION,
                request_fingerprint=f"fingerprint-{run_id}",
            ),
        )
        executions.transition_task(
            record.project_id,
            task_id,
            expected_status=TaskStatus.QUEUED,
            status=TaskStatus.RUNNING,
        )

    correlated_authorization = _authorization(
        services,
        record,
        agent_run,
        "authorization-correlated",
    )
    unrelated_authorization = _authorization(
        services,
        record,
        agent_run,
        "authorization-unrelated",
        run_id=unrelated_run_id,
        round_id="round-unrelated",
    )
    submission = await _query_after_deferred_setup_check(
        adapter,
        services,
        submission,
    )
    waiting = _workflow_record(services, record.submission_id)
    assert waiting.stage == "waiting_approval"

    command = TaskCommand(
        task_id=submission.handle.task_id,
        command_id="cancel-correlated",
        kind="cancel",
        payload={"reason": "Stop this workflow."},
        created_at=1001,
        updated_at=1001,
    )
    assert (await adapter.command(submission, command)).state == "accepted"
    assert (await adapter.command(submission, command)).state == "accepted"

    runs = CreatorAgentRunStore(services.root)
    assert runs.get(record.project_id, agent_run.run_id).status is (
        AgentRunStatus.CANCELLED
    )
    assert (
        executions.get_specialist_run(
            record.project_id,
            correlated_run_id,
        ).status
        is SpecialistRunStatus.CANCELLED
    )
    assert (
        executions.get_task(
            record.project_id,
            f"task-{correlated_run_id}",
        ).status
        is TaskStatus.CANCELLED
    )
    assert (
        executions.get_execution_authorization(
            record.project_id,
            correlated_authorization.authorization_id,
        ).status
        is ExecutionAuthorizationStatus.EXPIRED
    )

    assert (
        executions.get_specialist_run(
            record.project_id,
            unrelated_run_id,
        ).status
        is SpecialistRunStatus.RUNNING_MODEL
    )
    assert (
        executions.get_task(
            record.project_id,
            f"task-{unrelated_run_id}",
        ).status
        is TaskStatus.RUNNING
    )
    assert (
        executions.get_execution_authorization(
            record.project_id,
            unrelated_authorization.authorization_id,
        ).status
        is ExecutionAuthorizationStatus.PENDING
    )
    assert (
        services.sessions.get_goal(
            record.project_id,
            record.goal_id,
        ).status
        is CreatorGoalStatus.CANCELLED
    )
    assert (
        services.projects.read(record.project_id).etag == project_before.etag
    )

    cancelled = _workflow_record(services, record.submission_id)
    assert cancelled.stage == "cancelled"
    assert sum(event.stage == "cancelled" for event in cancelled.events) == 1
    assert runtime_cancellations == [
        (record.project_id, cancelled.correlated_run_ids),
        (record.project_id, cancelled.correlated_run_ids),
    ]


@pytest.mark.asyncio
async def test_cancellation_linearizes_before_publication_intent_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path / "creator")
    adapter = CreatorVideoWorkflowTaskAdapter(lambda: services)
    monkeypatch.setattr(
        pawapp_video_workflow,
        "notify_creator_agent_runtime",
        lambda _project_id: True,
    )
    before = _submission("create-video-cancel-before-publication")
    await adapter.submit(before)
    cancel_before = TaskCommand(
        task_id=before.handle.task_id,
        command_id="cancel-before",
        kind="cancel",
        payload={"reason": "Stop this workflow."},
        created_at=1001,
        updated_at=1001,
    )
    assert (await adapter.command(before, cancel_before)).state == "accepted"
    cancelled = _workflow_record(services, before.handle.submission_id)
    assert cancelled.stage == "cancelled"
    assert not cancelled.publication_committed
    cancel_status = await adapter.query_command(before, cancel_before)
    assert cancel_status.state == "accepted"

    after = _submission(
        "create-video-cancel-after-publication",
        task_id="host-create-video-task-2",
    )
    run_ref = await adapter.submit(after)
    record = _workflow_record(services, after.handle.submission_id)
    run = _agent_run(services, record, status=AgentRunStatus.SUCCEEDED)
    graph, _content = _install_final_video(services, record, run, "cancel")
    monkeypatch.setattr(
        pawapp_video_workflow,
        "derive_work_graph",
        lambda *_args, **_kwargs: graph,
    )
    await adapter.query(after)
    intent = _workflow_record(services, after.handle.submission_id)
    assert intent.publication_committed
    cancel_after = TaskCommand(
        task_id=after.handle.task_id,
        command_id="cancel-after",
        kind="cancel",
        payload={"reason": "Too late."},
        created_at=1002,
        updated_at=1002,
    )
    rejected = await adapter.command(after, cancel_after)
    assert rejected.model_dump(mode="json") == {
        "state": "rejected",
        "reason": "publication_committed",
    }

    accepted = _accepted_submission(after, run_ref)
    artifacts = await ArtifactStore.open(tmp_path / "host-artifacts")
    publish_event = [event async for event in adapter.attach(accepted)][-1]
    await adapter.materialize_event(accepted, publish_event, artifacts)
    succeeded = _workflow_record(services, after.handle.submission_id)
    assert succeeded.stage == "succeeded"
    assert (
        await adapter.command(after, cancel_after)
    ).reason == "publication_committed"

# -*- coding: utf-8 -*-
"""Authenticated project handoff and exact artifact grant invariants."""

import hashlib
import sqlite3

import pytest

from qwenpaw.pawapp.artifacts import ArtifactStore
from qwenpaw.pawapp.handoffs import HandoffStore
from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    ExecutorEvent,
    ExecutorRunRef,
    LocalizedText,
    TaskExperienceDefinition,
    TaskExperienceStepDefinition,
    TaskExperienceViewDefinition,
    TaskOrigin,
    TaskScope,
    TaskStore,
    TaskStoreError,
)


async def project_submission(tmp_path):
    scope = TaskScope(
        principal_id="alice",
        workspace_id="sales",
        app_id="qwenpaw-data",
    )
    action = ActionDescriptor(
        app_id="qwenpaw-data",
        action_id="analyze",
        summary="Analyze data",
        engagements=("delegated",),
        input_schema={"type": "object", "additionalProperties": True},
        output_types=("qwenpaw:file",),
        adapter_ref="test",
    )
    tasks = await TaskStore.open(tmp_path / "tasks.sqlite3")
    submission = await tasks.create(
        scope,
        action,
        request_id="request-1",
        inputs={"text": "Compare private revenue"},
        origin=TaskOrigin(
            engagement="delegated",
            origin_ref="chat-1",
            return_session_ref="session-1",
        ),
        experience=TaskExperienceDefinition(
            action_id="analyze",
            title=LocalizedText(default="Data analysis"),
            steps=(
                TaskExperienceStepDefinition(
                    id="analyze",
                    label=LocalizedText(default="Analyze"),
                ),
            ),
            views=(
                TaskExperienceViewDefinition(
                    id="summary",
                    label=LocalizedText(default="Summary"),
                    open_label=LocalizedText(default="Open analysis"),
                ),
            ),
            default_view_id="summary",
        ),
    )
    await tasks.begin_submission(scope, submission.handle.task_id)
    run = ExecutorRunRef(
        executor_id="data:test",
        session_id="analysis-session-1",
        run_id="run-1",
    )
    submission = await tasks.record_accepted(
        scope,
        submission.handle.task_id,
        run,
    )
    artifacts = await ArtifactStore.open(tmp_path / "artifacts")
    content = b"private report"
    ref = await artifacts.publish(
        submission,
        {
            "source_id": "report-1",
            "name": "report.md",
            "path": "reports/report.md",
            "media_type": "text/markdown",
            "size_bytes": len(content),
            "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        },
        content,
    )
    submission = await tasks.apply_event(
        scope,
        submission.handle.task_id,
        ExecutorEvent(
            run_ref=run,
            sequence=0,
            cursor="0",
            detail={
                "project_ref": {
                    "schema_version": 1,
                    "app_id": "qwenpaw-data",
                    "project_id": run.session_id,
                    "kind": "analysis-session",
                    "revision": 1,
                },
                "artifact_ref": ref.model_dump(mode="json"),
            },
        ),
    )
    return submission, artifacts, ref, content


async def test_handoff_is_idempotent_scoped_and_bounded(tmp_path):
    submission, artifacts, ref, _ = await project_submission(tmp_path)
    store = await HandoffStore.open(tmp_path / "handoffs.sqlite3", artifacts)

    first = await store.create(submission, target_app_id="creator")
    replay = await store.create(submission, target_app_id="creator")

    assert replay == first
    assert first.path == f"/apps/creator?handoff={first.handoff_id}"
    assert "analysis-session-1" not in first.path
    assert first.view_id == "summary"
    target = submission.handle.scope.model_copy(update={"app_id": "creator"})
    handoff = await store.resolve(target, first.handoff_id)
    assert handoff.context.goal == "Compare private revenue"
    assert handoff.context.project_ref == submission.handle.project_ref
    assert handoff.context.artifact_refs == (ref,)
    assert handoff.context.resume_ref == submission.handle.task_id
    assert handoff.context.view_id == "summary"
    assert "principal_id" not in handoff.context.model_dump(mode="json")

    for unauthorized in (
        target.model_copy(update={"principal_id": "mallory"}),
        target.model_copy(update={"workspace_id": "other"}),
        target.model_copy(update={"app_id": "other"}),
    ):
        with pytest.raises(TaskStoreError, match="handoff_not_found"):
            await store.resolve(unauthorized, first.handoff_id)

    connection = sqlite3.connect(store.path)
    try:
        denied = connection.execute(
            "SELECT count(*) FROM handoff_audit WHERE outcome = 'not_found'",
        ).fetchone()[0]
    finally:
        connection.close()
    assert denied == 3


async def test_artifact_collection_is_scoped_and_media_filtered(tmp_path):
    submission, artifacts, ref, _ = await project_submission(tmp_path)

    collection = await artifacts.list(
        submission.handle.scope,
        media_type="text/markdown",
    )
    assert collection.source == "host_artifacts"
    assert collection.app_id == "qwenpaw-data"
    assert collection.total_count == 1
    assert collection.items == (ref,)
    assert collection.next_cursor is None

    assert (
        await artifacts.list(
            submission.handle.scope,
            media_type="video/mp4",
        )
    ).total_count == 0
    assert (
        await artifacts.list(
            submission.handle.scope.model_copy(
                update={"principal_id": "mallory"},
            ),
        )
    ).total_count == 0

    with pytest.raises(TaskStoreError, match="invalid_artifact_cursor"):
        await artifacts.list(submission.handle.scope, cursor="not-a-cursor")


async def test_handoff_grants_only_exact_artifact_version(tmp_path):
    submission, artifacts, ref, content = await project_submission(tmp_path)
    creator = submission.handle.scope.model_copy(update={"app_id": "creator"})
    with pytest.raises(TaskStoreError, match="artifact_not_found"):
        await artifacts.read(creator, ref.artifact_id, ref.version)

    store = await HandoffStore.open(tmp_path / "handoffs.sqlite3", artifacts)
    action = await store.create(submission, target_app_id="creator")
    await store.resolve(creator, action.handoff_id)
    granted = await artifacts.read(creator, ref.artifact_id, ref.version)
    assert granted[1] == content

    with pytest.raises(TaskStoreError, match="artifact_not_found"):
        await artifacts.read(creator, ref.artifact_id, ref.version + 1)
    with pytest.raises(TaskStoreError, match="artifact_not_found"):
        await artifacts.read(
            creator.model_copy(update={"principal_id": "mallory"}),
            ref.artifact_id,
            ref.version,
        )


async def test_handoff_requires_project_and_rejects_rebinding(tmp_path):
    submission, artifacts, _, _ = await project_submission(tmp_path)
    store = await HandoffStore.open(tmp_path / "handoffs.sqlite3", artifacts)
    without_project = submission.model_copy(
        update={
            "handle": submission.handle.model_copy(
                update={"project_ref": None},
            ),
        },
    )
    with pytest.raises(TaskStoreError, match="project_unavailable"):
        await store.create(without_project, target_app_id="qwenpaw-data")

    tasks = await TaskStore.open(tmp_path / "tasks.sqlite3")
    with pytest.raises(TaskStoreError, match="project_ref_conflict"):
        await tasks.apply_event(
            submission.handle.scope,
            submission.handle.task_id,
            ExecutorEvent(
                run_ref=submission.handle.executor_run_ref,
                sequence=1,
                cursor="1",
                detail={
                    "project_ref": {
                        "schema_version": 1,
                        "app_id": "qwenpaw-data",
                        "project_id": "different-session",
                        "kind": "analysis-session",
                        "revision": 2,
                    },
                },
            ),
        )

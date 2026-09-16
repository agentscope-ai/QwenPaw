# -*- coding: utf-8 -*-
"""Immutable PawApp artifact publication and task linkage."""

from __future__ import annotations

import hashlib

import pytest

from qwenpaw.pawapp.artifacts import ArtifactStore
from qwenpaw.pawapp.tasks.continuation_store import ContinuationQueue
from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    ExecutorEvent,
    ExecutorRunRef,
    TaskOrigin,
    TaskScope,
    TaskStore,
    TaskStoreError,
)


async def accepted_submission(tmp_path):
    scope = TaskScope(
        principal_id="alice",
        workspace_id="default",
        app_id="qwenpaw-data",
    )
    action = ActionDescriptor(
        app_id="qwenpaw-data",
        action_id="analyze",
        summary="Analyze data",
        engagements=("delegated",),
        input_schema={"type": "object", "additionalProperties": False},
        output_types=("text/plain", "qwenpaw:file"),
        adapter_ref="test",
    )
    tasks = await TaskStore.open(tmp_path / "tasks.sqlite3")
    submission = await tasks.create(
        scope,
        action,
        request_id="request-1",
        inputs={},
        origin=TaskOrigin(
            engagement="delegated",
            origin_ref="chat-1",
            return_session_ref="session-1",
        ),
    )
    await tasks.begin_submission(scope, submission.handle.task_id)
    run = ExecutorRunRef(
        executor_id="data:test",
        session_id="data-session",
        run_id="data-run",
    )
    submission = await tasks.record_accepted(
        scope,
        submission.handle.task_id,
        run,
    )
    return tasks, submission, run


def source(content: bytes, *, source_id="source-1"):
    return {
        "source_id": source_id,
        "name": "report.md",
        "path": "reports/report.md",
        "media_type": "text/markdown",
        "size_bytes": len(content),
        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
    }


async def test_publication_is_immutable_versioned_and_scoped(tmp_path):
    _, submission, _ = await accepted_submission(tmp_path)
    artifacts = await ArtifactStore.open(tmp_path / "artifacts")
    first = await artifacts.publish(submission, source(b"first"), b"first")
    replay = await artifacts.publish(submission, source(b"first"), b"first")
    second = await artifacts.publish(
        submission,
        source(b"second", source_id="source-2"),
        b"second",
    )

    assert replay == first
    assert second.artifact_id == first.artifact_id
    assert (first.version, second.version) == (1, 2)
    first_read = await artifacts.read(
        submission.handle.scope,
        first.artifact_id,
        1,
    )
    second_read = await artifacts.read(
        submission.handle.scope,
        second.artifact_id,
        2,
    )
    assert first_read[1] == b"first"
    assert second_read[1] == b"second"

    other = submission.handle.scope.model_copy(
        update={"principal_id": "mallory"},
    )
    with pytest.raises(TaskStoreError, match="artifact_not_found"):
        await artifacts.read(other, first.artifact_id, first.version)

    with pytest.raises(TaskStoreError, match="artifact_source_conflict"):
        await artifacts.publish(
            submission,
            source(b"changed"),
            b"changed",
        )


async def test_task_commits_published_ref_and_terminal_result(tmp_path):
    tasks, submission, run = await accepted_submission(tmp_path)
    artifacts = await ArtifactStore.open(tmp_path / "artifacts")
    ref = await artifacts.publish(submission, source(b"report"), b"report")

    submission = await tasks.apply_event(
        submission.handle.scope,
        submission.handle.task_id,
        ExecutorEvent(
            run_ref=run,
            sequence=0,
            cursor="0",
            detail={"artifact_ref": ref.model_dump(mode="json")},
        ),
    )
    assert submission.handle.output_refs == (ref,)

    submission = await tasks.apply_event(
        submission.handle.scope,
        submission.handle.task_id,
        ExecutorEvent(
            run_ref=run,
            sequence=1,
            cursor="1",
            status="succeeded",
            text_result="Report ready",
        ),
    )
    assert submission.handle.status == "succeeded"
    assert submission.handle.output_refs == (ref,)
    reopened = await TaskStore.open(tasks.path)
    persisted = await reopened.get(
        submission.handle.scope,
        submission.handle.task_id,
    )
    assert persisted.handle.output_refs == (ref,)
    claim = await ContinuationQueue(reopened).claim()
    assert claim is not None
    assert claim.summary["output_refs"] == [ref.model_dump(mode="json")]

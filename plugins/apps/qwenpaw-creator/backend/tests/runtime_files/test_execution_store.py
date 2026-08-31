# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from domain.enums import (
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)
from services.runtime_files.errors import RuntimeFileValidationError
from services.runtime_files.execution_models import (
    ContinuationState,
    ExecutionAuthorizationRecord,
    ExecutionAuthorizationStatus,
    SpecialistRunRecord,
    TaskRecord,
)
from services.runtime_files.execution_store import (
    AuthorizationTokenConflict,
    ExecutionStateConflict,
    ExecutionStoreIntegrityError,
    ProjectExecutionStore,
)
from services.runtime_files.models import ReviewPolicy
from services.runtime_files.session_store import ProjectRuntimeSessionStore

pytestmark = pytest.mark.unit


PROJECT_ID = "project-1"
ROUND_ID = "round-1"
RUN_ID = "run-1"
REQUEST_ID = "request-1"
MESSAGE_ID = "message-1"


def _store(tmp_path: Path) -> ProjectExecutionStore:
    project_root = tmp_path / PROJECT_ID
    project_root.mkdir()
    (project_root / "project.json").write_text("{}\n", encoding="utf-8")
    return ProjectExecutionStore(tmp_path)


def _run(*, run_id: str = RUN_ID) -> SpecialistRunRecord:
    return SpecialistRunRecord(
        run_id=run_id,
        project_id=PROJECT_ID,
        round_id=ROUND_ID,
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_refs=["project://script"],
        input_generation=3,
        input_etag="sha256:input",
        caused_by_request_id=REQUEST_ID,
        caused_by_message_id=MESSAGE_ID,
        caused_by_message_seq=7,
        review_policy=ReviewPolicy.REQUIRE_REVIEW,
    )


def _task(*, task_id: str = "task-1", run_id: str = RUN_ID) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        project_id=PROJECT_ID,
        round_id=ROUND_ID,
        run_id=run_id,
        kind=TaskKind.COMPOSE,
        request_fingerprint="sha256:request",
        input_generation=3,
        input_etag="sha256:input",
        input_refs=["project://script"],
        caused_by_request_id=REQUEST_ID,
        caused_by_message_id=MESSAGE_ID,
        caused_by_message_seq=7,
        review_policy=ReviewPolicy.REQUIRE_REVIEW,
    )


def _authorization(**overrides) -> ExecutionAuthorizationRecord:
    record = ExecutionAuthorizationRecord(
        authorization_id="authorization-1",
        project_id=PROJECT_ID,
        round_id=ROUND_ID,
        run_id=RUN_ID,
        execution_request_id="execution-request-1",
        operation="generate_video",
        target_scope=["element:r2v-1"],
        authorization_token="secret-token",
        summary="Generate one candidate",
    )
    return record.model_copy(update=overrides) if overrides else record


def test_run_task_and_attempt_heads_use_atomic_json_and_jsonl(tmp_path):
    store = _store(tmp_path)
    store.create_specialist_run(_run())
    running = store.transition_specialist_run(
        PROJECT_ID,
        RUN_ID,
        expected_status=SpecialistRunStatus.QUEUED,
        status=SpecialistRunStatus.RUNNING_MODEL,
    )
    assert running.status is SpecialistRunStatus.RUNNING_MODEL

    store.create_task(_task())
    started = store.append_task_attempt(
        PROJECT_ID,
        "task-1",
        event_id="attempt-event-1",
        attempt_id="attempt-1",
        status="RUNNING",
        input={"prompt": "hello"},
    )
    assert started.attempt_seq == 1
    assert store.get_task(PROJECT_ID, "task-1").status is TaskStatus.RUNNING

    completed = store.append_task_attempt(
        PROJECT_ID,
        "task-1",
        event_id="attempt-event-2",
        attempt_id="attempt-1",
        status="SUCCEEDED",
        output={"assetId": "asset-1"},
    )
    assert completed.attempt_seq == 2
    final_task = store.get_task(PROJECT_ID, "task-1")
    assert final_task.status is TaskStatus.SUCCEEDED
    assert final_task.last_attempt_seq == 2
    assert final_task.result == {"assetId": "asset-1"}
    assert final_task.review_policy is ReviewPolicy.REQUIRE_REVIEW
    attempts = tmp_path / PROJECT_ID / "runtime" / "tasks" / "task-1"
    text = (attempts / "attempts.jsonl").read_text(encoding="utf-8")
    assert text.count("\n") == 2


def test_execution_write_does_not_wait_for_session_runtime_domain(tmp_path):
    store = _store(tmp_path)
    store.create_specialist_run(_run())
    sessions = ProjectRuntimeSessionStore(
        tmp_path.resolve(),
        lock_timeout_seconds=0.05,
    )

    with sessions._runtime_lock(PROJECT_ID):
        created = store.create_task(_task())

    assert created.task_id == "task-1"


def test_message_and_continuation_streams_are_ordered_and_inherit_provenance(
    tmp_path,
):
    store = _store(tmp_path)
    store.create_specialist_run(_run())
    store.transition_run(
        PROJECT_ID,
        RUN_ID,
        expected_status="QUEUED",
        status="RUNNING_MODEL",
    )
    store.create_task(_task())

    message = store.append_message(
        PROJECT_ID,
        RUN_ID,
        message_id="run-message-1",
        role="assistant",
        content_parts=[{"type": "text", "text": "working"}],
    )
    assert message.message_seq == 1
    assert message.caused_by_message_seq == 7

    waiting = store.append_continuation(
        PROJECT_ID,
        RUN_ID,
        event_id="continuation-event-1",
        continuation_id="continuation-1",
        continuation_token="opaque/token+is-not-a-path",
        state=ContinuationState.WAITING,
        task_id="task-1",
    )
    assert waiting.continuation_seq == 1
    waiting_status = store.get_run(PROJECT_ID, RUN_ID).status
    assert waiting_status is SpecialistRunStatus.WAITING_RUNTIME

    resumed = store.append_continuation(
        PROJECT_ID,
        RUN_ID,
        event_id="continuation-event-2",
        continuation_id="continuation-1",
        continuation_token="opaque/token+is-not-a-path",
        state=ContinuationState.RESUMED,
    )
    assert resumed.continuation_seq == 2
    resumed_status = store.get_run(PROJECT_ID, RUN_ID).status
    assert resumed_status is SpecialistRunStatus.RUNNING_MODEL
    assert store.get_run(PROJECT_ID, RUN_ID).last_continuation_seq == 2


def test_illegal_and_stale_state_transitions_are_rejected(tmp_path):
    store = _store(tmp_path)
    store.create_run(_run())
    with pytest.raises(ExecutionStateConflict, match="illegal"):
        store.transition_run(
            PROJECT_ID,
            RUN_ID,
            expected_status="QUEUED",
            status="SUCCEEDED",
        )

    store.transition_run(
        PROJECT_ID,
        RUN_ID,
        expected_status="QUEUED",
        status="RUNNING_MODEL",
    )
    with pytest.raises(ExecutionStateConflict, match="CAS conflict"):
        store.transition_run(
            PROJECT_ID,
            RUN_ID,
            expected_status="QUEUED",
            status="CANCELLED",
        )


def test_rejected_attempt_or_continuation_does_not_append_a_history_line(
    tmp_path,
):
    store = _store(tmp_path)
    store.create_run(_run())
    store.create_task(_task())
    runtime_root = tmp_path / PROJECT_ID / "runtime"
    store.transition_task(
        PROJECT_ID,
        "task-1",
        expected_status="QUEUED",
        status="CANCELLED",
    )
    with pytest.raises(ExecutionStateConflict, match="Task state"):
        store.append_attempt(
            PROJECT_ID,
            "task-1",
            event_id="invalid-attempt-event",
            attempt_id="invalid-attempt",
            status="RUNNING",
        )
    assert not (runtime_root / "tasks" / "task-1" / "attempts.jsonl").exists()


def test_attempt_replay_repairs_append_then_head_crash_gap(
    tmp_path,
    monkeypatch,
):
    store = _store(tmp_path)
    store.create_run(_run())
    store.create_task(_task())
    apply_head = store._apply_attempt_head_unlocked

    def crash_after_append(*_args, **_kwargs):
        raise RuntimeError("simulated crash after JSONL fsync")

    monkeypatch.setattr(
        store,
        "_apply_attempt_head_unlocked",
        crash_after_append,
    )
    with pytest.raises(RuntimeError, match="after JSONL fsync"):
        store.append_attempt(
            PROJECT_ID,
            "task-1",
            event_id="attempt-event-1",
            attempt_id="attempt-1",
            status="RUNNING",
        )
    assert store.get_task(PROJECT_ID, "task-1").last_attempt_seq == 0

    monkeypatch.setattr(store, "_apply_attempt_head_unlocked", apply_head)
    replay = store.append_attempt(
        PROJECT_ID,
        "task-1",
        event_id="attempt-event-1",
        attempt_id="attempt-1",
        status="RUNNING",
    )
    assert replay.attempt_seq == 1
    recovered = store.get_task(PROJECT_ID, "task-1")
    assert recovered.last_attempt_seq == 1
    assert len(store.list_attempts(PROJECT_ID, "task-1")) == 1


def test_authorization_decision_is_token_and_status_cas(tmp_path):
    store = _store(tmp_path)
    authorization = store.create_authorization(_authorization())
    assert authorization.status is ExecutionAuthorizationStatus.PENDING

    with pytest.raises(AuthorizationTokenConflict):
        store.decide_authorization(
            PROJECT_ID,
            authorization.authorization_id,
            authorization_token="wrong-token",
            status="REJECTED",
        )

    def decide(target: ExecutionAuthorizationStatus) -> str:
        try:
            store.decide_authorization(
                PROJECT_ID,
                authorization.authorization_id,
                authorization_token="secret-token",
                status=target,
            )
            return "won"
        except ExecutionStateConflict:
            return "conflict"

    targets = (
        ExecutionAuthorizationStatus.APPROVED,
        ExecutionAuthorizationStatus.REJECTED,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(decide, targets))
    assert sorted(outcomes) == ["conflict", "won"]


def test_quarantine_is_create_once_and_never_reclassifies_it(tmp_path):
    store = _store(tmp_path)
    store.create_run(_run())
    store.create_task(_task())

    first = store.quarantine_task_result(
        PROJECT_ID,
        "task-1",
        quarantine_id="quarantine-1",
        reason="INPUT_ETAG_CHANGED",
        result={"late": True},
    )
    assert first.replayed is False
    assert first.task.status is TaskStatus.QUARANTINED

    replay = store.quarantine_task_result(
        PROJECT_ID,
        "task-1",
        quarantine_id="different-retry-id",
        reason="INPUT_ETAG_CHANGED",
        result={"late": True},
    )
    assert replay.replayed is True
    assert replay.record.quarantine_id == "quarantine-1"
    with pytest.raises(
        ExecutionStoreIntegrityError,
        match="cannot change inherited review_policy",
    ):
        store.quarantine_task_result(
            PROJECT_ID,
            "task-1",
            reason="INPUT_ETAG_CHANGED",
            result={"late": True},
            review_policy=ReviewPolicy.AUTO_FIX,
        )


@pytest.mark.parametrize(
    ("project_id", "run_id"),
    [
        ("../escape", "run-1"),
        (PROJECT_ID, "../escape"),
    ],
)
def test_all_path_identifiers_reject_directory_traversal(
    tmp_path,
    project_id,
    run_id,
):
    store = _store(tmp_path)
    candidate = _run(run_id=run_id).model_copy(
        update={"project_id": project_id},
    )
    with pytest.raises(RuntimeFileValidationError):
        store.create_run(candidate)

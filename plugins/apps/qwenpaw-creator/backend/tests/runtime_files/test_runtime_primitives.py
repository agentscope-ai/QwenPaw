# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Runtime primitives: path safety, idempotency, record models, status bar."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import re

from pydantic import ValidationError
import pytest

from domain.enums import (
    CreatorSessionStatus,
    TaskKind,
    TaskStatus,
)
from services.runtime_files import (
    ChangeOrigin,
    ChangeRoundRecord,
    IdempotencyConflictError,
    IdempotencyRecordStore,
    IdempotencyStateConflictError,
    IdempotencyStatus,
    ProjectChangeKind,
    ReviewBoundary,
    ReviewOperation,
    ReviewPolicy,
    ReviewRecord,
    ReviewStatus,
    RuntimeFileValidationError,
    hashed_runtime_segment,
    require_safe_runtime_segment,
)
from services.runtime_files.execution_models import TaskRecord
from services.runtime_files.models import CreatorSessionRecord
from services.runtime_files.status_projection import build_agent_status_bar


pytestmark = pytest.mark.unit


def test_runtime_path_segment_rejects_traversal_and_control_characters():
    assert (
        require_safe_runtime_segment("review-1:decision.2")
        == "review-1:decision.2"
    )

    for unsafe in ("", ".", "..", "../round", "a/b", "a\\b", "line\nbreak"):
        with pytest.raises(RuntimeFileValidationError):
            require_safe_runtime_segment(unsafe)


def test_opaque_runtime_ids_are_hashed_into_a_stable_safe_segment():
    parts = (
        "review-decision",
        "../../persisted-round",
        "x/../../../../escaped",
    )
    first = hashed_runtime_segment(*parts)
    second = hashed_runtime_segment(*parts)

    assert first == second
    assert re.fullmatch(r"review-decision-[0-9a-f]{64}", first)
    assert "escaped" not in first


KEY = {
    "owner_id": "project-1",
    "scope": "POST /commands",
    "idempotency_key": "client-command-1",
}


def test_concurrent_reserve_has_exactly_one_creator_and_replays_completion(
    tmp_path,
):
    root = tmp_path / "runtime" / "commands" / "idempotency"
    request_hash = IdempotencyRecordStore.request_hash({"value": 1})

    def reserve():
        return IdempotencyRecordStore(root).reserve(
            **KEY,
            request_hash=request_hash,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        reservations = list(executor.map(lambda _index: reserve(), range(8)))

    assert sum(reservation.created for reservation in reservations) == 1

    completed = IdempotencyRecordStore(root).complete(
        **KEY,
        request_hash=request_hash,
        response={"body": {"ok": True}},
        response_status=202,
    )
    replay = reserve()
    assert completed.status is IdempotencyStatus.COMPLETED
    assert replay.created is False
    assert replay.record.response == {"body": {"ok": True}}


def test_idempotency_payload_drift_and_terminal_state_drift_are_conflicts(
    tmp_path,
):
    store = IdempotencyRecordStore(tmp_path / "idempotency")
    store.reserve(**KEY, request_hash="hash-a")
    with pytest.raises(IdempotencyConflictError):
        store.reserve(**KEY, request_hash="hash-b")

    store.fail(
        **KEY,
        request_hash="hash-a",
        error={"code": "FAILED"},
        response_status=500,
    )
    with pytest.raises(IdempotencyStateConflictError):
        store.complete(**KEY, request_hash="hash-a", response={"ok": True})


def boundary() -> ReviewBoundary:
    return ReviewBoundary(
        request_message_seq=2,
        request_id="request-2",
        interrupted_run_id="run-1",
        accepted_generation=3,
        accepted_etag="sha256:accepted",
        captured_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


def operation() -> ReviewOperation:
    return ReviewOperation(
        operation_id="operation-1",
        kind=ProjectChangeKind.UPDATE,
        json_pointer="/story/title",
        before_hash="sha256:before",
        after_hash="sha256:after",
        before="old",
        after="new",
    )


def test_only_review_capable_origins_can_require_review():
    record = ChangeRoundRecord(
        round_id="round-1",
        project_id="project-1",
        origin=ChangeOrigin.AGENTDOCK_INTERRUPT,
        review_policy=ReviewPolicy.REQUIRE_REVIEW,
        review_boundary=boundary(),
        caused_by_request_id="request-2",
        caused_by_message_seq=2,
    )
    assert record.review_boundary is not None

    with pytest.raises(ValidationError, match="only an AgentDock interrupt"):
        ChangeRoundRecord(
            round_id="round-2",
            project_id="project-1",
            origin=ChangeOrigin.INITIAL_CREATION,
            review_policy=ReviewPolicy.REQUIRE_REVIEW,
            review_boundary=boundary(),
        )
    with pytest.raises(ValidationError, match="cannot carry a ReviewBoundary"):
        ChangeRoundRecord(
            round_id="round-3",
            project_id="project-1",
            origin=ChangeOrigin.INITIAL_CREATION,
            review_policy=ReviewPolicy.AUTO_FIX,
            review_boundary=boundary(),
        )


def test_pending_review_requires_a_real_pending_runtime_operation():
    review = ReviewRecord(
        review_id="review-1",
        round_id="round-1",
        request_id="request-2",
        request_message_seq=2,
        interrupted_run_id="run-1",
        baseline_generation=3,
        baseline_etag="sha256:accepted",
        candidate_generation=4,
        candidate_etag="sha256:candidate",
        decision_token="token-1",
        operations=[operation()],
    )
    assert review.status is ReviewStatus.PENDING

    accepted = operation().model_copy(update={"decision": "ACCEPTED"})
    with pytest.raises(ValidationError, match="pending operation"):
        ReviewRecord.model_validate(
            review.model_copy(update={"operations": [accepted]}),
        )

    # Transition code commonly uses model_copy.  Persistence validation must
    # still reject a copied model whose cross-field state was not resolved.
    invalid_copy = review.model_copy(update={"status": ReviewStatus.RESOLVED})
    with pytest.raises(ValidationError, match="cannot contain pending"):
        ReviewRecord.model_validate(invalid_copy)


def _session(
    status: CreatorSessionStatus = CreatorSessionStatus.IDLE,
) -> CreatorSessionRecord:
    return CreatorSessionRecord(
        session_id="session-1",
        project_id="project-1",
        status=status,
        active_goal_id="goal-1",
        last_event_seq=17,
    )


def _task(*, status: TaskStatus, progress: float | None = None) -> TaskRecord:
    return TaskRecord(
        task_id="task-1",
        project_id="project-1",
        kind=TaskKind.ASSET_INGEST,
        status=status,
        request_fingerprint="fingerprint-1",
        progress=progress,
        input_refs=["element:edit-1"],
    )


def test_active_task_supplies_real_operation_progress_and_target() -> None:
    view = build_agent_status_bar(
        _session(),
        tasks=[_task(status=TaskStatus.RUNNING, progress=0.42)],
    )

    progress = view["progress"]
    assert progress["goalId"] == "goal-1"
    assert progress["phase"] == "source_ingest"
    assert progress["label"] == "附件入库中 · 42%"
    assert (progress["completed"], progress["total"]) == (42, 100)
    assert progress["elementId"] == "edit-1"
    assert progress["sourceEventSeq"] == 17
    assert view["activity"] == {
        "label": "附件入库中 · 42%",
        "runningTaskCount": 1,
    }


def test_every_task_kind_has_a_presentation_or_degrades() -> None:
    # Field run 2026-08-09: review_scene tasks 500'd the session
    # bootstrap and blanked AgentDock history. Every TaskKind must map,
    # and unknown kinds must degrade instead of raising.
    from services.runtime_files import status_projection

    # pylint: disable-next=protected-access
    presentation = status_projection._TASK_PRESENTATION  # noqa: SLF001
    for kind in TaskKind:
        assert kind in presentation, kind

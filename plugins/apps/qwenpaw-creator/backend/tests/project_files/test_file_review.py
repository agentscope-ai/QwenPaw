# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-variable
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from services.project_files.commit import ProjectCommitBoundary
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.project_files.review import (
    ProjectReviewService,
    ReviewDecisionConflict,
    ReviewDecisionItem,
    ReviewDecisionJournal,
    ReviewDecisionJournalState,
    ReviewDecisionRecoveryAction,
    ReviewRejectionAction,
    ReviewRejectionFeedback,
    render_rejection_feedback_message,
)
from services.project_files.store import ProjectStore
from services.project_files.store import ProjectNotFound
from services.runtime_files import hashed_runtime_segment
from services.runtime_files.models import (
    ReviewBoundary,
    ReviewStatus,
    RuntimeProjectState,
)
from services.runtime_files.models import ReviewOperationDecision
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.jsonl_store import DurableJsonlStore
from services.project_files.review import ReviewDecisionEvent


def _pending_review(tmp_path):
    store = ProjectStore(tmp_path.resolve())
    base = store.create(
        Project.new(project_id="project-1", name="Before", description="old"),
    )
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "After"
    candidate["description"] = "new"
    result = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        origin="agentdock_interrupt",
        review_policy="require_review",
        review_boundary=ReviewBoundary(
            request_message_seq=2,
            request_id="request-2",
            interrupted_run_id="run-1",
            accepted_generation=0,
            accepted_etag=base.etag,
        ),
        caused_by_request_id="request-2",
        caused_by_message_seq=2,
        round_id="round-2",
    )
    return store, base, result


def test_accept_does_not_rewrite_project_and_reject_is_compensating_cas(
    tmp_path,
) -> None:
    store, base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operations = {item.json_pointer: item for item in review.operations}
    service = ProjectReviewService(store)

    partial = service.decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[
            ReviewDecisionItem(
                operation_id=operations["/name"].operation_id,
                decision="ACCEPT",
            ),
        ],
    )
    assert partial.status is ReviewStatus.PENDING
    assert store.read("project-1").generation == committed.snapshot.generation

    resolved = service.decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=partial.decision_token,
        decisions=[
            ReviewDecisionItem(
                operation_id=operations["/description"].operation_id,
                decision="REJECT",
            ),
        ],
    )
    current = store.read("project-1")
    assert resolved.status is ReviewStatus.RESOLVED
    assert current.project.name == "After"
    assert current.project.description == base.project.description
    assert current.generation == committed.snapshot.generation + 1
    state = AtomicJsonRecordStore(
        tmp_path / "project-1" / "runtime" / "state.json",
        RuntimeProjectState,
    ).read()
    assert state.accepted_generation == current.generation


def test_rejection_feedback_is_durable_and_idempotent(tmp_path) -> None:
    store, _base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item for item in review.operations if item.json_pointer == "/name"
    )
    service = ProjectReviewService(store)
    feedback = ReviewRejectionFeedback(
        action=ReviewRejectionAction.UNDO_AND_REGENERATE,
        feedbackNote="  人物状态不对；保持身份一致后重做  ",
    )

    resolved = service.decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[
            ReviewDecisionItem(
                operation_id=operation.operation_id,
                decision="REJECT",
            ),
        ],
        rejection_feedback=feedback,
        decision_id="decision-with-feedback",
    )
    journal = service.get_decision_journal(
        "project-1",
        review.review_id,
        "decision-with-feedback",
    )

    assert resolved.status is ReviewStatus.PENDING
    assert journal.state is ReviewDecisionJournalState.FINALIZED
    assert journal.rejection_feedback is not None
    assert journal.rejection_feedback.feedback_note == "人物状态不对；保持身份一致后重做"
    assert [target.json_pointers for target in journal.rejection_targets] == [
        ["/name"],
    ]
    assert journal.event is not None
    assert journal.event.rejection_feedback == journal.rejection_feedback
    message = render_rejection_feedback_message(journal)
    assert message is not None
    assert "明确要求重新生成" in message
    assert "人物状态不对" in message
    assert "用户反馈与调整要求" in message

    replay = service.decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[
            ReviewDecisionItem(
                operation_id=operation.operation_id,
                decision="REJECT",
            ),
        ],
        rejection_feedback=feedback,
        decision_id="decision-with-feedback",
    )
    assert replay == resolved

    with pytest.raises(
        ReviewDecisionConflict,
        match="different Review request",
    ):
        service.decide(
            project_id="project-1",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[
                ReviewDecisionItem(
                    operation_id=operation.operation_id,
                    decision="REJECT",
                ),
            ],
            rejection_feedback=ReviewRejectionFeedback(
                action=ReviewRejectionAction.UNDO_ONLY,
            ),
            decision_id="decision-with-feedback",
        )


def test_legacy_rejection_feedback_fields_remain_readable() -> None:
    feedback = ReviewRejectionFeedback(
        action=ReviewRejectionAction.UNDO_AND_REGENERATE,
        problemNote="  人物状态不对  ",
        regenerationInstruction="  保持身份一致后重做  ",
    )

    assert feedback.feedback_note is None
    assert feedback.problem_note == "人物状态不对"
    assert feedback.regeneration_instruction == "保持身份一致后重做"
    serialized = feedback.model_dump(mode="json", by_alias=True)
    assert serialized["feedbackNote"] is None


def test_rejection_targets_collapse_artifact_operations_by_variant(
    tmp_path,
) -> None:
    _store, _base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    original = review.operations[0]
    locator = {
        "page": "assets",
        "assetId": "char:haaland",
        "mediaType": "image",
        "artifactKind": "visual_asset_image",
        "artifactVersionId": "artifact-version-poor",
    }
    version_operation = original.model_copy(
        update={
            "operation_id": "operation-version",
            "json_pointer": (
                "/assets/artifact_versions_by_id/artifact-version-poor"
            ),
            "target_ref": "visual-entity:char:haaland",
            "after": {
                "version_id": "artifact-version-poor",
                "name": "哈兰德 · 落魄时期",
                "owner_ref": "visual-entity:char:haaland",
                "metadata": {
                    "targetRef": "visual-entity:char:haaland",
                    "variantId": "poor-era",
                },
            },
            "ui_locator": locator,
        },
    )
    slot_operation = original.model_copy(
        update={
            "operation_id": "operation-slot",
            "json_pointer": (
                "/assets/artifact_slots_by_id/slot-poor/selected_version_id"
            ),
            "target_ref": "visual-entity:char:haaland",
            "after": "artifact-version-poor",
            "ui_locator": locator,
        },
    )
    synthetic = review.model_copy(
        update={"operations": [slot_operation, version_operation]},
    )

    targets = ProjectReviewService._rejection_targets(
        review=synthetic,
        decisions=[
            ReviewDecisionItem(
                operation_id="operation-slot",
                decision="REJECT",
            ),
            ReviewDecisionItem(
                operation_id="operation-version",
                decision="REJECT",
            ),
        ],
    )

    assert len(targets) == 1
    assert targets[0].label == "哈兰德 · 落魄时期"
    assert targets[0].target_ref == "visual-entity:char:haaland"
    assert targets[0].variant_id == "poor-era"
    assert targets[0].artifact_version_id == "artifact-version-poor"
    assert len(targets[0].json_pointers) == 2


def test_review_decision_refuses_to_overwrite_newer_user_value(
    tmp_path,
) -> None:
    store, _base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item for item in review.operations if item.json_pointer == "/name"
    )
    current = store.read("project-1")
    candidate = current.project.model_dump(mode="json")
    candidate["name"] = "User newer value"
    ProjectCommitBoundary(store).commit(
        base=current,
        candidate=candidate,
        origin="frontend_edit",
        advance_accepted_baseline=False,
    )

    with pytest.raises(ReviewDecisionConflict, match="token is stale"):
        ProjectReviewService(store).decide(
            project_id="project-1",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[
                ReviewDecisionItem(
                    operation_id=operation.operation_id,
                    decision="REJECT",
                ),
            ],
        )
    assert store.read("project-1").project.name == "User newer value"


def test_frontend_edit_supersedes_only_overlapping_pending_operation(
    tmp_path,
) -> None:
    store, _base, committed = _pending_review(tmp_path)
    current = store.read("project-1")
    candidate = current.project.model_dump(mode="json")
    candidate["name"] = "User authoritative value"

    ProjectCommitBoundary(store).commit(
        base=current,
        candidate=candidate,
        origin="frontend_edit",
    )

    review = ProjectReviewService(store).active("project-1")
    assert review is not None
    operations = {item.json_pointer: item for item in review.operations}
    assert (
        operations["/name"].decision
        is ReviewOperationDecision.SUPERSEDED_BY_USER_EDIT
    )
    assert (
        operations["/description"].decision is ReviewOperationDecision.PENDING
    )
    state = AtomicJsonRecordStore(
        tmp_path / "project-1" / "runtime" / "state.json",
        RuntimeProjectState,
    ).read()
    assert state.accepted_generation == 0
    assert state.active_round_id == "round-2"


def test_reject_hashes_opaque_decision_and_round_ids_before_path_use(
    tmp_path,
) -> None:
    store, _base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item for item in review.operations if item.json_pointer == "/name"
    )
    malicious_decision_id = "x/../../../../escaped"

    ProjectReviewService(store).decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[
            ReviewDecisionItem(
                operation_id=operation.operation_id,
                decision="REJECT",
            ),
        ],
        decision_id=malicious_decision_id,
    )

    expected_round = hashed_runtime_segment(
        "review-decision",
        review.round_id,
        malicious_decision_id,
    )
    assert (
        tmp_path
        / "project-1"
        / "runtime"
        / "change-rounds"
        / expected_round
        / "round.json"
    ).is_file()
    assert not (tmp_path / "escaped").exists()


def test_missing_project_review_decision_does_not_create_runtime_tree(
    tmp_path,
) -> None:
    store = ProjectStore(tmp_path.resolve())

    with pytest.raises(ProjectNotFound):
        ProjectReviewService(store).decide(
            project_id="missing",
            review_id="review-1",
            decision_token="token",
            decisions=[
                ReviewDecisionItem(
                    operation_id="operation-1",
                    decision="ACCEPT",
                ),
            ],
            decision_id="decision-1",
        )

    assert not (tmp_path / "missing").exists()


def test_reject_retry_recovers_when_crash_follows_compensating_commit(
    tmp_path,
    monkeypatch,
) -> None:
    store, base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item for item in review.operations if item.json_pointer == "/name"
    )
    decision = ReviewDecisionItem(
        operation_id=operation.operation_id,
        decision="REJECT",
    )
    decision_id = "decision-crash-after-project-commit"
    service = ProjectReviewService(store)
    original_persist = service._persist_project_applied
    failed = False

    def crash_before_applied_journal(*args):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("injected crash after compensating commit")
        return original_persist(*args)

    monkeypatch.setattr(
        service,
        "_persist_project_applied",
        crash_before_applied_journal,
    )
    with pytest.raises(RuntimeError, match="injected crash"):
        service.decide(
            project_id="project-1",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[decision],
            decision_id=decision_id,
        )

    applied = store.read("project-1")
    assert applied.project.name == base.project.name
    assert applied.generation == committed.snapshot.generation + 1
    decision_key = hashed_runtime_segment("decision", decision_id)
    journal_store = AtomicJsonRecordStore(
        tmp_path
        / "project-1"
        / "runtime"
        / "reviews"
        / review.review_id
        / "decision-transactions"
        / decision_key
        / "journal.json",
        ReviewDecisionJournal,
    )
    assert journal_store.read().state is ReviewDecisionJournalState.PREPARED

    resolved = service.decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[decision],
        decision_id=decision_id,
    )
    assert resolved.status is ReviewStatus.PENDING
    assert store.read("project-1").generation == applied.generation
    assert journal_store.read().state is ReviewDecisionJournalState.FINALIZED
    events = DurableJsonlStore(
        tmp_path
        / "project-1"
        / "runtime"
        / "reviews"
        / review.review_id
        / "decisions.jsonl",
        ReviewDecisionEvent,
    ).read_records()
    assert [event.decision_id for event in events].count(decision_id) == 1

    replayed = service.decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[decision],
        decision_id=decision_id,
    )
    assert replayed == resolved
    assert store.read("project-1").generation == applied.generation


def test_reject_retry_finishes_project_applied_journal_after_review_write_crash(
    tmp_path,
    monkeypatch,
) -> None:
    store, base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item
        for item in review.operations
        if item.json_pointer == "/description"
    )
    decision = ReviewDecisionItem(
        operation_id=operation.operation_id,
        decision="REJECT",
    )
    decision_id = "decision-crash-before-review-write"
    service = ProjectReviewService(store)
    original_write = service._write_review
    failed = False

    def crash_before_review_write(*args):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("injected review write crash")
        return original_write(*args)

    monkeypatch.setattr(service, "_write_review", crash_before_review_write)
    with pytest.raises(RuntimeError, match="review write crash"):
        service.decide(
            project_id="project-1",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[decision],
            decision_id=decision_id,
        )

    applied = store.read("project-1")
    assert applied.project.description == base.project.description
    assert applied.generation == committed.snapshot.generation + 1
    decision_key = hashed_runtime_segment("decision", decision_id)
    journal_store = AtomicJsonRecordStore(
        tmp_path
        / "project-1"
        / "runtime"
        / "reviews"
        / review.review_id
        / "decision-transactions"
        / decision_key
        / "journal.json",
        ReviewDecisionJournal,
    )
    assert (
        journal_store.read().state
        is ReviewDecisionJournalState.PROJECT_APPLIED
    )

    resolved = service.decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[decision],
        decision_id=decision_id,
    )
    assert resolved.status is ReviewStatus.PENDING
    assert store.read("project-1").generation == applied.generation
    assert journal_store.read().state is ReviewDecisionJournalState.FINALIZED


def test_startup_recovers_prepared_decision_without_repeating_compensation(
    tmp_path,
    monkeypatch,
) -> None:
    store, base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item for item in review.operations if item.json_pointer == "/name"
    )
    decision = ReviewDecisionItem(
        operation_id=operation.operation_id,
        decision="REJECT",
    )
    decision_id = "decision-startup-after-compensation"
    service = ProjectReviewService(store)

    def crash_before_applied_journal(*_args):
        raise RuntimeError("injected crash before decision journal promotion")

    monkeypatch.setattr(
        service,
        "_persist_project_applied",
        crash_before_applied_journal,
    )
    with pytest.raises(RuntimeError, match="journal promotion"):
        service.decide(
            project_id="project-1",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[decision],
            decision_id=decision_id,
        )

    compensated = store.read("project-1")
    assert compensated.project.name == base.project.name
    assert compensated.generation == committed.snapshot.generation + 1

    restarted = CreatorFileServices.create(tmp_path.resolve())

    assert restarted.startup_recovery.ok
    assert restarted.startup_review_recovery.ok
    outcome = next(
        item
        for project in restarted.startup_review_recovery.projects
        for item in project.outcomes
        if item.decision_id == decision_id
    )
    assert outcome.action is ReviewDecisionRecoveryAction.FINALIZED
    assert outcome.state_before is ReviewDecisionJournalState.PREPARED
    assert outcome.state_after is ReviewDecisionJournalState.FINALIZED
    # The stable compensation transaction is recognized and never executed a
    # second time during startup recovery.
    assert store.read("project-1") == compensated

    decision_key = hashed_runtime_segment("decision", decision_id)
    journal = AtomicJsonRecordStore(
        tmp_path
        / "project-1"
        / "runtime"
        / "reviews"
        / review.review_id
        / "decision-transactions"
        / decision_key
        / "journal.json",
        ReviewDecisionJournal,
    ).read()
    assert journal.state is ReviewDecisionJournalState.FINALIZED
    events = DurableJsonlStore(
        tmp_path
        / "project-1"
        / "runtime"
        / "reviews"
        / review.review_id
        / "decisions.jsonl",
        ReviewDecisionEvent,
    ).read_records()
    assert [event.decision_id for event in events].count(decision_id) == 1


def test_startup_recovery_preserves_user_edit_after_prepared_decision_crash(
    tmp_path,
    monkeypatch,
) -> None:
    store, _base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item for item in review.operations if item.json_pointer == "/name"
    )
    decision = ReviewDecisionItem(
        operation_id=operation.operation_id,
        decision="REJECT",
    )
    decision_id = "decision-user-edit-after-prepared"
    service = ProjectReviewService(store)

    def crash_before_applied_journal(*_args):
        raise RuntimeError("injected crash before decision journal promotion")

    monkeypatch.setattr(
        service,
        "_persist_project_applied",
        crash_before_applied_journal,
    )
    with pytest.raises(RuntimeError, match="journal promotion"):
        service.decide(
            project_id="project-1",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[decision],
            decision_id=decision_id,
        )

    current = store.read("project-1")
    candidate = current.project.model_dump(mode="json")
    candidate["name"] = "User authoritative value"
    user_result = ProjectCommitBoundary(store).commit(
        base=current,
        candidate=candidate,
        origin="frontend_edit",
    )
    before_restart = store.read("project-1")
    assert before_restart == user_result.snapshot

    restarted = CreatorFileServices.create(tmp_path.resolve())

    assert restarted.startup_review_recovery.ok
    assert store.read("project-1") == before_restart
    assert store.read("project-1").project.name == "User authoritative value"
    recovered = restarted.reviews.get("project-1", review.review_id)
    recovered_operation = next(
        item
        for item in recovered.operations
        if item.operation_id == operation.operation_id
    )
    assert (
        recovered_operation.decision
        is ReviewOperationDecision.SUPERSEDED_BY_USER_EDIT
    )
    decision_key = hashed_runtime_segment("decision", decision_id)
    journal = AtomicJsonRecordStore(
        tmp_path
        / "project-1"
        / "runtime"
        / "reviews"
        / review.review_id
        / "decision-transactions"
        / decision_key
        / "journal.json",
        ReviewDecisionJournal,
    ).read()
    assert journal.state is ReviewDecisionJournalState.FINALIZED
    assert journal.final_review == recovered


def test_startup_rebases_project_applied_decision_onto_user_supersession(
    tmp_path,
    monkeypatch,
) -> None:
    store, _base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item for item in review.operations if item.json_pointer == "/name"
    )
    decision = ReviewDecisionItem(
        operation_id=operation.operation_id,
        decision="REJECT",
    )
    decision_id = "decision-user-edit-after-project-applied"
    service = ProjectReviewService(store)

    def crash_before_review_write(*_args):
        raise RuntimeError("injected crash before Review write")

    monkeypatch.setattr(service, "_write_review", crash_before_review_write)
    with pytest.raises(RuntimeError, match="Review write"):
        service.decide(
            project_id="project-1",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[decision],
            decision_id=decision_id,
        )

    current = store.read("project-1")
    candidate = current.project.model_dump(mode="json")
    candidate["name"] = "User value after applied journal"
    ProjectCommitBoundary(store).commit(
        base=current,
        candidate=candidate,
        origin="frontend_edit",
    )
    before_restart = store.read("project-1")

    restarted = CreatorFileServices.create(tmp_path.resolve())

    assert restarted.startup_review_recovery.ok
    assert store.read("project-1") == before_restart
    recovered = restarted.reviews.get("project-1", review.review_id)
    recovered_operation = next(
        item
        for item in recovered.operations
        if item.operation_id == operation.operation_id
    )
    assert (
        recovered_operation.decision
        is ReviewOperationDecision.SUPERSEDED_BY_USER_EDIT
    )
    decision_key = hashed_runtime_segment("decision", decision_id)
    journal = AtomicJsonRecordStore(
        tmp_path
        / "project-1"
        / "runtime"
        / "reviews"
        / review.review_id
        / "decision-transactions"
        / decision_key
        / "journal.json",
        ReviewDecisionJournal,
    ).read()
    assert journal.state is ReviewDecisionJournalState.FINALIZED
    assert journal.final_review == recovered


def test_new_decision_id_is_rejected_while_same_review_journal_is_active(
    tmp_path,
    monkeypatch,
) -> None:
    store, _base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item for item in review.operations if item.json_pointer == "/name"
    )
    decision = ReviewDecisionItem(
        operation_id=operation.operation_id,
        decision="ACCEPT",
    )
    service = ProjectReviewService(store)
    original_persist = service._persist_project_applied

    def crash_before_applied_journal(*_args):
        raise RuntimeError("injected active decision crash")

    monkeypatch.setattr(
        service,
        "_persist_project_applied",
        crash_before_applied_journal,
    )
    with pytest.raises(RuntimeError, match="active decision crash"):
        service.decide(
            project_id="project-1",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[decision],
            decision_id="decision-active-first",
        )

    with pytest.raises(
        ReviewDecisionConflict,
        match="active decision journal",
    ):
        service.decide(
            project_id="project-1",
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[decision],
            decision_id="decision-active-second",
        )

    transactions_root = (
        tmp_path
        / "project-1"
        / "runtime"
        / "reviews"
        / review.review_id
        / "decision-transactions"
    )
    decision_dirs = [
        item for item in transactions_root.iterdir() if item.is_dir()
    ]
    assert len(decision_dirs) == 1
    first_key = hashed_runtime_segment("decision", "decision-active-first")
    assert decision_dirs[0].name == first_key
    journal_store = AtomicJsonRecordStore(
        decision_dirs[0] / "journal.json",
        ReviewDecisionJournal,
    )
    assert journal_store.read().state is ReviewDecisionJournalState.PREPARED

    monkeypatch.setattr(service, "_persist_project_applied", original_persist)
    service.decide(
        project_id="project-1",
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[decision],
        decision_id="decision-active-first",
    )
    assert journal_store.read().state is ReviewDecisionJournalState.FINALIZED


def test_concurrent_new_decision_waits_then_rejects_active_journal(
    tmp_path,
    monkeypatch,
) -> None:
    store, _base, committed = _pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = next(
        item for item in review.operations if item.json_pointer == "/name"
    )
    decision = ReviewDecisionItem(
        operation_id=operation.operation_id,
        decision="ACCEPT",
    )
    service = ProjectReviewService(store)
    original_persist = service._persist_project_applied
    first_prepared = Event()
    second_started = Event()
    release_first = Event()

    def pause_then_crash(_store, journal):
        if journal.decision_id == "decision-concurrent-first":
            first_prepared.set()
            assert second_started.wait(timeout=5)
            assert release_first.wait(timeout=5)
            raise RuntimeError("injected concurrent decision crash")
        return original_persist(_store, journal)

    monkeypatch.setattr(service, "_persist_project_applied", pause_then_crash)

    def call(decision_id: str):
        if decision_id == "decision-concurrent-second":
            second_started.set()
        try:
            service.decide(
                project_id="project-1",
                review_id=review.review_id,
                decision_token=review.decision_token,
                decisions=[decision],
                decision_id=decision_id,
            )
        except Exception as exc:  # returned to the asserting thread
            return exc
        return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(call, "decision-concurrent-first")
        assert first_prepared.wait(timeout=5)
        second = executor.submit(call, "decision-concurrent-second")
        assert second_started.wait(timeout=5)
        release_first.set()
        first_error = first.result(timeout=10)
        second_error = second.result(timeout=10)

    assert isinstance(first_error, RuntimeError)
    assert "concurrent decision crash" in str(first_error)
    assert isinstance(second_error, ReviewDecisionConflict)
    assert "active decision journal" in str(second_error)

    transactions_root = (
        tmp_path
        / "project-1"
        / "runtime"
        / "reviews"
        / review.review_id
        / "decision-transactions"
    )
    decision_dirs = [
        item for item in transactions_root.iterdir() if item.is_dir()
    ]
    assert len(decision_dirs) == 1
    journal = AtomicJsonRecordStore(
        decision_dirs[0] / "journal.json",
        ReviewDecisionJournal,
    ).read()
    assert journal.decision_id == "decision-concurrent-first"
    assert journal.state is ReviewDecisionJournalState.PREPARED

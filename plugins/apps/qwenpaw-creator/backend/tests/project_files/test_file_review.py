# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-variable
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from services.project_files.commit import ProjectCommitBoundary
from services.project_files.facade import CreatorFileServices
from services.project_files.review import (
    ProjectReviewService,
    ReviewDecisionConflict,
    ReviewDecisionEvent,
    ReviewDecisionItem,
    ReviewDecisionJournal,
    ReviewDecisionJournalState,
    ReviewRejectionAction,
    ReviewRejectionFeedback,
)
from services.project_files.store import ProjectNotFound, ProjectStore
from services.runtime_files import hashed_runtime_segment
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.jsonl_store import DurableJsonlStore
from services.runtime_files.models import (
    ReviewOperationDecision,
    ReviewStatus,
)

from .conftest import make_pending_review, read_state


def _operation(review, pointer):
    return next(o for o in review.operations if o.json_pointer == pointer)


def _item(operation, decision="REJECT"):
    return ReviewDecisionItem(
        operation_id=operation.operation_id,
        decision=decision,
    )


def _decide(service, review, decisions, **kwargs):
    kwargs.setdefault("decision_token", review.decision_token)
    return service.decide(
        project_id="project-1",
        review_id=review.review_id,
        decisions=decisions,
        **kwargs,
    )


def _decision_transactions_root(tmp_path, review_id):
    reviews = tmp_path / "project-1" / "runtime" / "reviews"
    return reviews / review_id / "decision-transactions"


def _decision_journal_store(tmp_path, review_id, decision_id):
    decision_key = hashed_runtime_segment("decision", decision_id)
    return AtomicJsonRecordStore(
        _decision_transactions_root(tmp_path, review_id)
        / decision_key
        / "journal.json",
        ReviewDecisionJournal,
    )


def _decision_events(tmp_path, review_id):
    reviews = tmp_path / "project-1" / "runtime" / "reviews"
    path = reviews / review_id / "decisions.jsonl"
    return DurableJsonlStore(path, ReviewDecisionEvent).read_records()


def test_accept_does_not_rewrite_project_and_reject_is_compensating_cas(
    tmp_path,
) -> None:
    store, base, committed = make_pending_review(tmp_path)
    review = committed.review
    assert review is not None
    service = ProjectReviewService(store)

    partial = _decide(
        service,
        review,
        [_item(_operation(review, "/name"), "ACCEPT")],
    )
    assert partial.status is ReviewStatus.PENDING
    assert store.read("project-1").generation == committed.snapshot.generation

    resolved = _decide(
        service,
        review,
        [_item(_operation(review, "/description"))],
        decision_token=partial.decision_token,
    )
    current = store.read("project-1")
    assert resolved.status is ReviewStatus.RESOLVED
    assert current.project.name == "After"
    assert current.project.description == base.project.description
    assert current.generation == committed.snapshot.generation + 1
    assert read_state(store).accepted_generation == current.generation


def test_rejection_feedback_is_durable_and_idempotent(tmp_path) -> None:
    store, _base, committed = make_pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = _operation(review, "/name")
    service = ProjectReviewService(store)
    feedback = ReviewRejectionFeedback(
        action=ReviewRejectionAction.UNDO_AND_REGENERATE,
        feedbackNote="  人物状态不对；保持身份一致后重做  ",
    )

    resolved = _decide(
        service,
        review,
        [_item(operation)],
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

    replay = _decide(
        service,
        review,
        [_item(operation)],
        rejection_feedback=feedback,
        decision_id="decision-with-feedback",
    )
    assert replay == resolved

    with pytest.raises(
        ReviewDecisionConflict,
        match="different Review request",
    ):
        _decide(
            service,
            review,
            [_item(operation)],
            rejection_feedback=ReviewRejectionFeedback(
                action=ReviewRejectionAction.UNDO_ONLY,
            ),
            decision_id="decision-with-feedback",
        )


def test_review_decision_refuses_to_overwrite_newer_user_value(
    tmp_path,
) -> None:
    store, _base, committed = make_pending_review(tmp_path)
    review = committed.review
    assert review is not None
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
        _decide(
            ProjectReviewService(store),
            review,
            [_item(_operation(review, "/name"))],
        )
    assert store.read("project-1").project.name == "User newer value"


def test_reject_hashes_opaque_decision_and_round_ids_before_path_use(
    tmp_path,
) -> None:
    store, _base, committed = make_pending_review(tmp_path)
    review = committed.review
    assert review is not None
    malicious_decision_id = "x/../../../../escaped"

    _decide(
        ProjectReviewService(store),
        review,
        [_item(_operation(review, "/name"))],
        decision_id=malicious_decision_id,
    )

    expected_round = hashed_runtime_segment(
        "review-decision",
        review.round_id,
        malicious_decision_id,
    )
    rounds = tmp_path / "project-1" / "runtime" / "change-rounds"
    assert (rounds / expected_round / "round.json").is_file()
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
                ReviewDecisionItem(operation_id="op-1", decision="ACCEPT"),
            ],
            decision_id="decision-1",
        )

    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    ("crash_method", "crash_match", "json_pointer", "parked_state"),
    [
        # Crash between the compensating Project commit and the decision
        # journal promotion: the journal parks at PREPARED.
        pytest.param(
            "_persist_project_applied",
            "injected crash after compensating commit",
            "/name",
            ReviewDecisionJournalState.PREPARED,
            id="crash-follows-compensating-commit",
        ),
        # Crash between the applied journal write and the Review write: the
        # journal parks at PROJECT_APPLIED.
        pytest.param(
            "_write_review",
            "injected review write crash",
            "/description",
            ReviewDecisionJournalState.PROJECT_APPLIED,
            id="crash-before-review-write",
        ),
    ],
)
def test_reject_retry_recovers_after_mid_decision_crash(
    tmp_path,
    monkeypatch,
    crash_method,
    crash_match,
    json_pointer,
    parked_state,
) -> None:
    store, base, committed = make_pending_review(tmp_path)
    review = committed.review
    assert review is not None
    decision = _item(_operation(review, json_pointer))
    decision_id = f"decision-crash-at{crash_method}"
    service = ProjectReviewService(store)
    original = getattr(service, crash_method)
    failed = False

    def crash_once(*args):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError(crash_match)
        return original(*args)

    monkeypatch.setattr(service, crash_method, crash_once)
    with pytest.raises(RuntimeError, match=crash_match):
        _decide(service, review, [decision], decision_id=decision_id)

    # The compensating Project commit is durable before either crash point.
    applied = store.read("project-1")
    field = json_pointer.lstrip("/")
    assert getattr(applied.project, field) == getattr(base.project, field)
    assert applied.generation == committed.snapshot.generation + 1
    journal_store = _decision_journal_store(
        tmp_path,
        review.review_id,
        decision_id,
    )
    assert journal_store.read().state is parked_state

    resolved = _decide(service, review, [decision], decision_id=decision_id)
    assert resolved.status is ReviewStatus.PENDING
    assert store.read("project-1").generation == applied.generation
    assert journal_store.read().state is ReviewDecisionJournalState.FINALIZED
    events = _decision_events(tmp_path, review.review_id)
    assert [event.decision_id for event in events].count(decision_id) == 1

    replayed = _decide(service, review, [decision], decision_id=decision_id)
    assert replayed == resolved
    assert store.read("project-1").generation == applied.generation


def test_startup_preserves_user_edit_after_decision_crash(
    tmp_path,
    monkeypatch,
) -> None:
    # PROJECT_APPLIED crash window: startup rebases the Review fact onto the
    # user's supersession.
    store, _base, committed = make_pending_review(tmp_path)
    review = committed.review
    assert review is not None
    operation = _operation(review, "/name")
    decision_id = "decision-user-edit-after-project-applied"
    service = ProjectReviewService(store)

    def crash(*_args):
        raise RuntimeError("injected crash before Review write")

    monkeypatch.setattr(service, "_write_review", crash)
    with pytest.raises(RuntimeError, match="before Review write"):
        _decide(service, review, [_item(operation)], decision_id=decision_id)

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
    journal = _decision_journal_store(
        tmp_path,
        review.review_id,
        decision_id,
    ).read()
    assert journal.state is ReviewDecisionJournalState.FINALIZED
    assert journal.final_review == recovered


def test_concurrent_new_decision_waits_then_rejects_active_journal(
    tmp_path,
    monkeypatch,
) -> None:
    store, _base, committed = make_pending_review(tmp_path)
    review = committed.review
    assert review is not None
    decision = _item(_operation(review, "/name"), "ACCEPT")
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
            _decide(service, review, [decision], decision_id=decision_id)
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

    transactions_root = _decision_transactions_root(
        tmp_path,
        review.review_id,
    )
    decision_dirs = [
        item for item in transactions_root.iterdir() if item.is_dir()
    ]
    assert len(decision_dirs) == 1
    journal_store = AtomicJsonRecordStore(
        decision_dirs[0] / "journal.json",
        ReviewDecisionJournal,
    )
    journal = journal_store.read()
    assert journal.decision_id == "decision-concurrent-first"
    assert journal.state is ReviewDecisionJournalState.PREPARED

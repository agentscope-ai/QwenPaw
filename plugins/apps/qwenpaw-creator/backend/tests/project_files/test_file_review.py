# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-variable
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import pytest

from services.project_files.commit import ProjectCommitBoundary
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ElementLocation,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
)
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

from .conftest import (
    make_pending_review,
    make_store,
    read_review,
    read_round,
    read_state,
    review_boundary,
    review_commit_kwargs,
)


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

    # A later edit in the same running round starts from the value the user
    # already kept, not from the original pre-round value.
    candidate = current.project.model_dump(mode="json")
    candidate["name"] = "Further revision"
    revised = ProjectCommitBoundary(store).commit(
        base=current,
        candidate=candidate,
        round_id=review.round_id,
        **review_commit_kwargs(
            read_round(store, review.round_id).review_boundary,
        ),
    )
    _decide(
        service,
        revised.review,
        [_item(_operation(revised.review, "/name"))],
    )
    assert store.read("project-1").project.name == "After"


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
    assert "/name" in journal.runtime_feedback_message
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


@pytest.mark.parametrize("accepted_parent", [False, True])
def test_same_round_nested_edits_remain_reviewable(tmp_path, accepted_parent):
    store, base = make_store(tmp_path)
    commits = ProjectCommitBoundary(store)
    service = ProjectReviewService(store)
    candidate = base.project.model_dump(mode="json")
    candidate["visual"]["entities"] = {
        "order": ["char:lulu"],
        "items": {
            "char:lulu": {
                "entity_id": "char:lulu",
                "kind": "character",
                "name": "Lulu",
                "required_variant_ids": [],
            },
        },
    }
    metadata = review_commit_kwargs(review_boundary(base))
    created = commits.commit(
        base=base,
        candidate=candidate,
        round_id="draft-round",
        **metadata,
    )
    parent_pointer = "/visual/entities/items/char:lulu"
    parent = _operation(created.review, parent_pointer)
    if accepted_parent:
        _decide(service, created.review, [_item(parent, "ACCEPT")])
    candidate = created.snapshot.project.model_dump(mode="json")
    candidate["visual"]["entities"]["items"]["char:lulu"][
        "description"
    ] = "Smooth, no fur"
    updated = commits.commit(
        base=created.snapshot,
        candidate=candidate,
        round_id="draft-round",
        **metadata,
    )
    pointer = (
        parent_pointer + "/description" if accepted_parent else parent_pointer
    )
    if accepted_parent:
        assert (
            _operation(updated.review, parent_pointer).decision
            is ReviewOperationDecision.ACCEPTED
        )
    else:
        assert not any(
            o.json_pointer.startswith(parent_pointer + "/")
            for o in updated.review.operations
        )
    _decide(
        service,
        updated.review,
        [_item(_operation(updated.review, pointer))],
    )
    entities = store.read("project-1").project.visual.entities
    if accepted_parent:
        assert entities.items["char:lulu"].description == ""
    else:
        assert entities.items == {} and entities.order == []


@pytest.mark.parametrize("restore_deleted", [False, True])
def test_partial_entity_rejection_preserves_collection_order(
    tmp_path,
    restore_deleted,
):
    store, base = make_store(tmp_path)
    candidate = base.project.model_dump(mode="json")
    entities = candidate["visual"]["entities"]
    entities["items"] = {
        key: {
            "entity_id": key,
            "kind": "character",
            "name": key,
            "required_variant_ids": [],
        }
        for key in ("char:lulu", "char:duck")
    }
    entities["order"] = ["char:lulu", "char:duck"]
    if restore_deleted:
        base = (
            ProjectCommitBoundary(store)
            .commit(
                base=base,
                candidate=candidate,
                origin="frontend_edit",
            )
            .snapshot
        )
        candidate = base.project.model_dump(mode="json")
        del candidate["visual"]["entities"]["items"]["char:lulu"]
        candidate["visual"]["entities"]["order"] = ["char:duck"]
    committed = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        round_id="round-entity",
        **review_commit_kwargs(review_boundary(base)),
    )
    service = ProjectReviewService(store)
    review = committed.review
    partial = _decide(
        service,
        review,
        [
            _item(_operation(review, "/visual/entities/items/char:lulu")),
        ],
    )
    current = store.read("project-1").project.visual.entities
    assert current.order == (
        ["char:lulu", "char:duck"] if restore_deleted else ["char:duck"]
    )
    assert set(current.items) == set(current.order)

    # The remaining order decision must still be actionable after its
    # membership changed as part of the per-entity rollback.
    _decide(
        service,
        partial,
        [_item(_operation(partial, "/visual/entities/order"))],
    )
    current = store.read("project-1").project.visual.entities
    assert set(current.items) == set(current.order)


def test_aborted_compensation_does_not_block_a_fresh_review_decision(
    tmp_path,
    monkeypatch,
):
    store, _base, committed = make_pending_review(tmp_path)
    service = ProjectReviewService(store)
    review = committed.review
    decisions = [_item(_operation(review, "/name"))]
    commit = service.commits.commit

    def invalid_compensation(**kwargs):
        kwargs["candidate"]["visual"]["entities"]["order"] = ["missing-entity"]
        return commit(**kwargs)

    monkeypatch.setattr(service.commits, "commit", invalid_compensation)
    with pytest.raises(ValueError, match="order must contain"):
        _decide(service, review, decisions, decision_id="failed-decision")
    monkeypatch.setattr(service.commits, "commit", commit)

    assert service.recover_project("project-1").ok
    assert (
        service.get_decision_journal(
            "project-1",
            review.review_id,
            "failed-decision",
        ).state
        is ReviewDecisionJournalState.ABORTED
    )
    with pytest.raises(ReviewDecisionConflict, match="aborted"):
        _decide(service, review, decisions, decision_id="failed-decision")
    _decide(service, review, decisions, decision_id="fresh-decision")
    assert store.read("project-1").project.name == "Before"


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


def test_decision_ignores_leftover_directory_without_journal(tmp_path) -> None:
    """A failed publish must not brick every later decision.

    ``atomic_create_bytes`` creates the decision directory before it stages
    the journal, so a staging failure (e.g. the Windows MAX_PATH temp path in
    #8163) leaves a ``decision-*`` directory with no ``journal.json``.  The
    active-decision guard used to raise on that leftover for every later
    attempt, turning one transient write failure into a Review that can never
    be decided.
    """
    store, _base, committed = make_pending_review(tmp_path)
    review = committed.review
    assert review is not None
    service = ProjectReviewService(store)

    abandoned_id = "decision-abandoned-publish"
    leftover = _decision_transactions_root(
        tmp_path,
        review.review_id,
    ) / hashed_runtime_segment("decision", abandoned_id)
    leftover.mkdir(parents=True)
    assert not (leftover / "journal.json").exists()

    resolved = _decide(service, review, [_item(_operation(review, "/name"))])

    assert resolved.status is ReviewStatus.PENDING
    assert (
        _decision_journal_store(
            tmp_path,
            review.review_id,
            abandoned_id,
        ).read_or_none()
        is None
    )


def test_decision_still_rejects_unreadable_existing_journal(tmp_path) -> None:
    """A journal that exists but cannot be read still fails closed."""
    store, _base, committed = make_pending_review(tmp_path)
    review = committed.review
    assert review is not None
    service = ProjectReviewService(store)

    corrupt = _decision_transactions_root(
        tmp_path,
        review.review_id,
    ) / hashed_runtime_segment("decision", "decision-corrupt-journal")
    corrupt.mkdir(parents=True)
    (corrupt / "journal.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ReviewDecisionConflict, match="inconsistent"):
        _decide(service, review, [_item(_operation(review, "/name"))])


def _seed_element(store, base):
    """Give ``project-1`` one R2V element carrying no artifacts yet."""
    project = base.project.model_copy(deep=True)
    element = TimelineElement(
        element_id="el-1",
        label="猫追老鼠",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="猫发现老鼠后追逐",
            storyboard_prompt="动画分镜",
            video_prompt="动画，猫追逐老鼠",
        ),
    )
    project.timelines.items["timeline:main"].elements_by_id["el-1"] = element
    return (
        ProjectCommitBoundary(store)
        .commit(
            base=base,
            candidate=project.model_dump(mode="json"),
            origin="runtime_task",
        )
        .snapshot
    )


def _commit_artifact_round(store, base, *, round_id, seq):
    """A review-gated round that introduces artifact version ``av-1``."""
    candidate = base.project.model_dump(mode="json")
    created_at = datetime.now(UTC).isoformat()
    checksum = "a" * 64
    assets = candidate["assets"]
    assets["files_by_id"]["file-1"] = {
        "file_id": "file-1",
        "kind": "artifact_payload",
        "relative_uri": "assets/artifacts/sb-1.png",
        "sha256": checksum,
        "size_bytes": 1024,
        "media_type": "image/png",
        "created_at": created_at,
    }
    assets["artifact_versions_by_id"]["av-1"] = {
        "version_id": "av-1",
        "slot_id": "slot-1",
        "kind": "r2v_storyboard_image",
        "owner_ref": "element:el-1",
        "name": "分镜图 1",
        "file_id": "file-1",
        "checksum": checksum,
        "based_on_generation": 0,
        "created_at": created_at,
    }
    assets["artifact_slots_by_id"]["slot-1"] = {
        "slot_id": "slot-1",
        "kind": "r2v_storyboard_image",
        "owner_ref": "element:el-1",
        "version_ids": ["av-1"],
        "selected_version_id": "av-1",
    }
    return ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        round_id=round_id,
        **review_commit_kwargs(review_boundary(base, seq=seq)),
    )


def _main_element(candidate):
    return candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "el-1"
    ]


def test_reject_prunes_a_later_round_reference_to_its_artifact(
    tmp_path,
) -> None:
    """Issue #8592: rejecting a round that created an artifact version must
    also drop the references later pending rounds added to it.

    Both rounds legitimately stay pending (commit.py allows that).  The old
    compensation only reverted the rejected round's own operations, so the
    surviving reference made Project validation fail; the decision was never
    published and every retry returned the same opaque 422 forever.
    """
    store, base = make_store(tmp_path, name="Initial")
    seeded = _seed_element(store, base)
    artifact_round = _commit_artifact_round(
        store,
        seeded,
        round_id="round-artifact",
        seq=2,
    )
    review = artifact_round.review
    assert review is not None

    candidate = artifact_round.snapshot.project.model_dump(mode="json")
    _main_element(candidate)["creation"][
        "storyboard_reference_version_ids"
    ] = ["av-1"]
    reference_round = ProjectCommitBoundary(store).commit(
        base=artifact_round.snapshot,
        candidate=candidate,
        round_id="round-reference",
        **review_commit_kwargs(
            review_boundary(artifact_round.snapshot, seq=3),
        ),
    )
    assert reference_round.review is not None

    # A newer round rotates the pending Review's decision token, exactly as
    # the UI re-reads it before deciding.
    review = read_review(store, "round-artifact")
    resolved = _decide(
        ProjectReviewService(store),
        review,
        [_item(operation) for operation in review.operations],
    )

    assert resolved.status is ReviewStatus.RESOLVED
    project = store.read("project-1").project
    assert "av-1" not in project.assets.artifact_versions_by_id
    assert "slot-1" not in project.assets.artifact_slots_by_id
    element = project.timelines.items["timeline:main"].elements_by_id["el-1"]
    assert element.creation.storyboard_reference_version_ids == []


def test_reject_reports_a_structural_reference_instead_of_an_empty_422(
    tmp_path,
) -> None:
    """A render binding cannot be pruned without destroying accepted work.

    The rejection must fail with the element the user has to resolve and
    leave the Review decidable, instead of publishing nothing and returning
    the bare pydantic 422 (``details: {}``) issue #8592 reported.
    """
    store, base = make_store(tmp_path, name="Initial")
    seeded = _seed_element(store, base)
    artifact_round = _commit_artifact_round(
        store,
        seeded,
        round_id="round-artifact",
        seq=2,
    )
    review = artifact_round.review
    assert review is not None

    candidate = artifact_round.snapshot.project.model_dump(mode="json")
    _main_element(candidate)["render_source"] = {
        "type": "artifact_version",
        "version_id": "av-1",
    }
    ProjectCommitBoundary(store).commit(
        base=artifact_round.snapshot,
        candidate=candidate,
        round_id="round-render",
        **review_commit_kwargs(
            review_boundary(artifact_round.snapshot, seq=3),
        ),
    )

    review = read_review(store, "round-artifact")
    generation_before_decision = store.read("project-1").generation
    with pytest.raises(ReviewDecisionConflict) as excinfo:
        _decide(
            ProjectReviewService(store),
            review,
            [_item(operation) for operation in review.operations],
        )

    assert "无法回滚" in str(excinfo.value)
    assert "el-1" in str(excinfo.value)
    # Nothing durable was published, so a different decision still works.
    assert store.read("project-1").generation == generation_before_decision


def _seed_element_output(store, base):
    """Give ``el-1`` a named output slot holding an unselected ``av-2``.

    A slot may legally keep versions without selecting one, so restoring
    this state leaves an ``element_output`` render source pointing at a
    slot whose selection is gone.
    """
    candidate = base.project.model_dump(mode="json")
    created_at = datetime.now(UTC).isoformat()
    checksum = "b" * 64
    assets = candidate["assets"]
    assets["files_by_id"]["file-2"] = {
        "file_id": "file-2",
        "kind": "artifact_payload",
        "relative_uri": "assets/artifacts/video-2.mp4",
        "sha256": checksum,
        "size_bytes": 1024,
        "media_type": "video/mp4",
        "created_at": created_at,
    }
    assets["artifact_versions_by_id"]["av-2"] = {
        "version_id": "av-2",
        "slot_id": "slot-out",
        "kind": "element_video",
        "owner_ref": "element:el-1",
        "name": "已接受视频",
        "file_id": "file-2",
        "checksum": checksum,
        "based_on_generation": 0,
        "created_at": created_at,
        "duration_seconds": 4.0,
    }
    assets["artifact_slots_by_id"]["slot-out"] = {
        "slot_id": "slot-out",
        "kind": "element_video",
        "owner_ref": "element:el-1",
        "version_ids": ["av-2"],
        "selected_version_id": None,
    }
    _main_element(candidate)["outputs"] = {"main": {"slot_id": "slot-out"}}
    return (
        ProjectCommitBoundary(store)
        .commit(
            base=base,
            candidate=candidate,
            origin="runtime_task",
        )
        .snapshot
    )


def _commit_version_next_to_accepted(store, base, *, round_id, seq):
    """A review-gated round that selects a new ``av-1`` in ``slot-out``."""
    candidate = base.project.model_dump(mode="json")
    created_at = datetime.now(UTC).isoformat()
    checksum = "d" * 64
    assets = candidate["assets"]
    assets["files_by_id"]["file-1"] = {
        "file_id": "file-1",
        "kind": "artifact_payload",
        "relative_uri": "assets/artifacts/video-1.mp4",
        "sha256": checksum,
        "size_bytes": 1024,
        "media_type": "video/mp4",
        "created_at": created_at,
    }
    assets["artifact_versions_by_id"]["av-1"] = {
        "version_id": "av-1",
        "slot_id": "slot-out",
        "kind": "element_video",
        "owner_ref": "element:el-1",
        "name": "新视频",
        "file_id": "file-1",
        "checksum": checksum,
        "based_on_generation": 0,
        "created_at": created_at,
        "duration_seconds": 4.0,
    }
    slot = assets["artifact_slots_by_id"]["slot-out"]
    slot["version_ids"].append("av-1")
    slot["selected_version_id"] = "av-1"
    return ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        round_id=round_id,
        **review_commit_kwargs(review_boundary(base, seq=seq)),
    )


def test_reject_prunes_i2v_and_s2v_exact_version_inputs(tmp_path) -> None:
    """Issue #8592: i2v/s2v take exact ArtifactVersion inputs, not lists.

    Project validation never checks them, so a leftover id after a rollback
    would stay invisible until the Element renders and fails on a version
    that no longer exists.
    """
    store, base = make_store(tmp_path, name="Initial")
    seeded = _seed_element(store, base)
    artifact_round = _commit_artifact_round(
        store,
        seeded,
        round_id="round-artifact",
        seq=2,
    )
    assert artifact_round.review is not None

    candidate = artifact_round.snapshot.project.model_dump(mode="json")
    elements = candidate["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]
    elements["el-1"]["creation"] = {
        "type": "i2v",
        "narrative": "猫发现老鼠",
        "video_prompt": "动画，猫追老鼠",
        "first_frame_version_id": "av-1",
    }
    elements["el-2"] = {
        "element_id": "el-2",
        "span": {"start_tick": 5_000, "duration_tick": 4_000},
        "location": {},
        "creation": {
            "type": "s2v",
            "portrait_version_id": "av-1",
            "audio_version_id": "av-1",
        },
    }
    ProjectCommitBoundary(store).commit(
        base=artifact_round.snapshot,
        candidate=candidate,
        round_id="round-exact-refs",
        **review_commit_kwargs(
            review_boundary(artifact_round.snapshot, seq=3),
        ),
    )

    review = read_review(store, "round-artifact")
    resolved = _decide(
        ProjectReviewService(store),
        review,
        [_item(operation) for operation in review.operations],
    )

    assert resolved.status is ReviewStatus.RESOLVED
    project = store.read("project-1").project
    elements = project.timelines.items["timeline:main"].elements_by_id
    assert "av-1" not in project.assets.artifact_versions_by_id
    assert elements["el-1"].creation.first_frame_version_id is None
    assert elements["el-2"].creation.portrait_version_id is None
    assert elements["el-2"].creation.audio_version_id is None


def test_reject_refuses_an_overlay_whose_payload_is_the_artifact(
    tmp_path,
) -> None:
    """A text-free overlay uses the artifact as its only payload.

    Pruning that reference would leave a document Project validation
    rejects, so the decision names the Element the user has to fill in.
    """
    store, base = make_store(tmp_path, name="Initial")
    seeded = _seed_element(store, base)
    artifact_round = _commit_artifact_round(
        store,
        seeded,
        round_id="round-artifact",
        seq=2,
    )
    assert artifact_round.review is not None

    candidate = artifact_round.snapshot.project.model_dump(mode="json")
    _main_element(candidate)["creation"] = {
        "type": "overlay",
        "reference_version_ids": ["av-1"],
    }
    ProjectCommitBoundary(store).commit(
        base=artifact_round.snapshot,
        candidate=candidate,
        round_id="round-overlay",
        **review_commit_kwargs(
            review_boundary(artifact_round.snapshot, seq=3),
        ),
    )

    review = read_review(store, "round-artifact")
    generation_before_decision = store.read("project-1").generation
    with pytest.raises(ReviewDecisionConflict) as excinfo:
        _decide(
            ProjectReviewService(store),
            review,
            [_item(operation) for operation in review.operations],
        )

    message = str(excinfo.value)
    assert "无法回滚" in message
    assert "el-1" in message
    assert "唯一素材" in message
    assert store.read("project-1").generation == generation_before_decision


def test_reject_refuses_a_render_whose_slot_loses_its_selection(
    tmp_path,
) -> None:
    """The slot keeps another version, but the rendered one is rolled back.

    ``element_output`` then has no selected version at all; the rejection
    must name that element and slot instead of failing with a bare
    pydantic message.
    """
    store, base = make_store(tmp_path, name="Initial")
    seeded = _seed_element(store, base)
    seeded = _seed_element_output(store, seeded)
    artifact_round = _commit_version_next_to_accepted(
        store,
        seeded,
        round_id="round-artifact",
        seq=2,
    )
    assert artifact_round.review is not None

    candidate = artifact_round.snapshot.project.model_dump(mode="json")
    candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "el-2"
    ] = {
        "element_id": "el-2",
        "span": {"start_tick": 5_000, "duration_tick": 4_000},
        "location": {},
        "creation": {"type": "r2v", "video_prompt": "复用上一段视频"},
        "render_source": {
            "type": "element_output",
            "element_id": "el-1",
            "output_name": "main",
        },
    }
    ProjectCommitBoundary(store).commit(
        base=artifact_round.snapshot,
        candidate=candidate,
        round_id="round-render-output",
        **review_commit_kwargs(
            review_boundary(artifact_round.snapshot, seq=3),
        ),
    )

    review = read_review(store, "round-artifact")
    with pytest.raises(ReviewDecisionConflict) as excinfo:
        _decide(
            ProjectReviewService(store),
            review,
            [_item(operation) for operation in review.operations],
        )

    message = str(excinfo.value)
    assert "无法回滚" in message
    assert "el-2" in message
    assert "slot-out" in message

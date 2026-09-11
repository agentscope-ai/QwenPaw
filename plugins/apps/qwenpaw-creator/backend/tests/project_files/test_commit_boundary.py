# -*- coding: utf-8 -*-
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison
from __future__ import annotations

import threading

import pytest

from services.project_files.commit import (
    ProjectCommitBoundary,
    ProjectCommitError,
    ProtectedFieldError,
)
from services.project_files.json_pointer import JsonCasConflict
from services.project_files.review import (
    ProjectReviewService,
    ReviewDecisionItem,
)
from services.runtime_files.errors import FieldBlockConflictError
from services.runtime_files.field_blocks import FieldBlockStore
from services.runtime_files.models import (
    ReviewOperationDecision,
    ReviewStatus,
)

from .conftest import (
    make_store,
    read_review,
    read_state,
    review_boundary,
    review_commit_kwargs,
    runtime_root,
)


def test_commit_publishes_project_changeset_and_accepted_state(
    tmp_path,
) -> None:
    store, base = make_store(tmp_path)
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Updated"

    result = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
    )

    assert result.snapshot.generation == 1
    assert store.read("project-1").project.name == "Updated"
    assert [c.json_pointer for c in result.changeset.changes] == ["/name"]
    state = read_state(store)
    assert state.accepted_generation == 1
    assert state.accepted_etag == result.snapshot.etag
    assert result.review is None


def test_disjoint_commits_from_one_base_merge(tmp_path) -> None:
    store, base = make_store(tmp_path)
    first = base.project.model_dump(mode="json")
    first["name"] = "Name A"
    ProjectCommitBoundary(store).commit(
        base=base,
        candidate=first,
        origin="frontend_edit",
    )

    second = base.project.model_dump(mode="json")
    second["description"] = "Description B"
    result = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=second,
        origin="runtime_task",
    )

    assert result.snapshot.generation == 2
    assert result.snapshot.project.name == "Name A"
    assert result.snapshot.project.description == "Description B"


def test_runtime_finalization_is_serialized_in_project_generation_order(
    tmp_path,
    monkeypatch,
) -> None:
    store, base = make_store(tmp_path)
    boundary = ProjectCommitBoundary(store)
    first_candidate = base.project.model_dump(mode="json")
    first_candidate["name"] = "First"
    second_candidate = base.project.model_dump(mode="json")
    second_candidate["description"] = "Second"
    first_finalizing = threading.Event()
    release_first = threading.Event()
    second_done = threading.Event()
    errors: list[BaseException] = []
    original_record_review = boundary._record_review

    def delayed_record_review(**kwargs):
        if kwargs["snapshot"].generation == 1:
            first_finalizing.set()
            assert release_first.wait(timeout=2)
        return original_record_review(**kwargs)

    monkeypatch.setattr(boundary, "_record_review", delayed_record_review)

    def run_commit(candidate, origin, done=None):
        try:
            boundary.commit(base=base, candidate=candidate, origin=origin)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            if done is not None:
                done.set()

    first_thread = threading.Thread(
        target=run_commit,
        args=(first_candidate, "runtime_task"),
    )
    second_thread = threading.Thread(
        target=run_commit,
        args=(second_candidate, "frontend_edit", second_done),
    )
    first_thread.start()
    assert first_finalizing.wait(timeout=2)
    second_thread.start()
    assert not second_done.wait(timeout=0.1)
    release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not errors
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    current = store.read("project-1")
    state = read_state(store)
    assert current.generation == 2
    assert current.project.name == "First"
    assert current.project.description == "Second"
    assert state.last_project_generation == 2
    assert state.accepted_generation == 2


def test_same_field_commits_from_one_base_conflict(tmp_path) -> None:
    store, base = make_store(tmp_path)
    first = base.project.model_dump(mode="json")
    first["name"] = "Name A"
    ProjectCommitBoundary(store).commit(
        base=base,
        candidate=first,
        origin="frontend_edit",
    )
    second = base.project.model_dump(mode="json")
    second["name"] = "Name B"

    with pytest.raises(JsonCasConflict) as caught:
        ProjectCommitBoundary(store).commit(
            base=base,
            candidate=second,
            origin="runtime_task",
        )
    assert caught.value.conflicts[0]["pointer"] == "/name"


def test_identical_retry_archives_safe_aborted_transaction(
    tmp_path,
    monkeypatch,
) -> None:
    store, base = make_store(tmp_path)
    boundary = ProjectCommitBoundary(store)
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Retried"
    original_replace = store.replace

    def fail_before_publish(*args, **kwargs):
        raise RuntimeError("injected pre-publish failure")

    monkeypatch.setattr(store, "replace", fail_before_publish)
    with pytest.raises(RuntimeError, match="pre-publish"):
        boundary.commit(
            base=base,
            candidate=candidate,
            origin="runtime_task",
            round_id="retry-round",
            transaction_id="retry-transaction",
        )
    monkeypatch.setattr(store, "replace", original_replace)

    result = boundary.commit(
        base=base,
        candidate=candidate,
        origin="runtime_task",
        round_id="retry-round",
        transaction_id="retry-transaction",
    )

    assert result.snapshot.project.name == "Retried"
    assert result.snapshot.generation == 1
    history = runtime_root(store) / "transaction-history" / "aborted"
    archived = list(history.iterdir())
    assert len(archived) == 1
    assert archived[0].name.startswith("retry-transaction.")


def test_commit_boundary_enforces_field_block_at_publish_time(
    tmp_path,
) -> None:
    store, base = make_store(tmp_path)
    blocks = FieldBlockStore(runtime_root(store) / "locks" / "fields")
    block = blocks.acquire(
        project_id="project-1",
        json_pointer="/name",
        owner_kind="user",
        owner_id="browser-1",
        base_field_hash="sha256:before",
        ttl_seconds=30,
    )
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Blocked"

    with pytest.raises(FieldBlockConflictError):
        ProjectCommitBoundary(store).commit(
            base=base,
            candidate=candidate,
            origin="runtime_task",
        )
    assert store.read("project-1") == base

    result = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
        block_token=block.token,
    )
    assert result.snapshot.project.name == "Blocked"


def test_candidate_cannot_change_runtime_metadata(tmp_path) -> None:
    store, base = make_store(tmp_path)
    candidate = base.project.model_dump(mode="json")
    candidate["generation"] = 99

    with pytest.raises(ProtectedFieldError) as caught:
        ProjectCommitBoundary(store).commit(
            base=base,
            candidate=candidate,
            origin="runtime_task",
        )
    assert caught.value.pointers == ["/generation"]


def test_character_voice_binding_is_runtime_only(tmp_path) -> None:
    """Only Runtime tasks may write voice bindings; agents cannot fabricate
    a voice_id through generic JSON edits after a failed enrollment."""

    store, base = make_store(tmp_path)
    seeded = base.project.model_dump(mode="json")
    seeded["visual"]["entities"]["items"]["char:hero"] = {
        "entity_id": "char:hero",
        "kind": "character",
        "name": "Hero",
        "description": "",
        "continuity": "",
        "required_variant_ids": [],
        "variants": {"items": {}, "order": []},
        "selected_artifact_version_id": None,
        "voice": None,
    }
    seeded["visual"]["entities"]["order"] = ["char:hero"]
    base = (
        ProjectCommitBoundary(store)
        .commit(
            base=base,
            candidate=seeded,
            origin="runtime_task",
        )
        .snapshot
    )

    candidate = base.project.model_dump(mode="json")
    binding = {
        "voice_id": "fabricated-voice-001",
        "target_model": "qwen3-tts-vc",
        "preferred_name": "hero",
        "sample_source_version_id": None,
        "enrollment_key": "k",
        "created_at": "2026-07-30T00:00:00Z",
    }
    candidate["visual"]["entities"]["items"]["char:hero"]["voice"] = binding

    for origin in ("agentdock_interrupt", "frontend_edit"):
        with pytest.raises(ProtectedFieldError):
            ProjectCommitBoundary(store).commit(
                base=base,
                candidate=candidate,
                origin=origin,
            )

    # The enrollment executor path (a Runtime task) stays allowed.
    result = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        origin="runtime_task",
    )
    written = result.snapshot.project.visual.entities.items["char:hero"]
    assert written.voice is not None
    assert written.voice.voice_id == "fabricated-voice-001"


def test_commit_ids_cannot_escape_runtime_directories(tmp_path) -> None:
    store, base = make_store(tmp_path)
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Unsafe"
    outside = tmp_path / "escaped"

    for arguments in (
        {"transaction_id": "../escaped"},
        {"transaction_id": "safe", "round_id": "x/../../escaped"},
        {"transaction_id": "safe", "round_id": "bad\\segment"},
        {"transaction_id": "safe", "round_id": "bad\x00segment"},
    ):
        with pytest.raises(ProjectCommitError, match="unsafe Runtime path"):
            ProjectCommitBoundary(store).commit(
                base=base,
                candidate=candidate,
                origin="runtime_task",
                **arguments,
            )

    assert not outside.exists()


def test_only_agentdock_active_interrupt_creates_review(tmp_path) -> None:
    store, base = make_store(tmp_path)
    candidate = base.project.model_dump(mode="json")
    candidate["description"] = "AgentDock requested change"

    result = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        round_id="round-2",
        **review_commit_kwargs(review_boundary(base)),
    )

    assert result.review is not None
    ops = result.review.operations
    assert [o.json_pointer for o in ops] == ["/description"]
    assert read_review(store, "round-2").request_id == "request-2"
    state = read_state(store)
    assert state.accepted_generation == 0
    assert state.last_project_generation == 1


def test_user_edit_supersedes_pending_operation_in_coexisting_reviews(
    tmp_path,
) -> None:
    # Multiple pending reviews coexist; a direct user edit must supersede
    # the touched operation even in a review that active_round_id does not
    # currently point at.
    store, base = make_store(tmp_path)
    commit = ProjectCommitBoundary(store)
    first_candidate = base.project.model_dump(mode="json")
    first_candidate["description"] = "Reviewed description"
    first = commit.commit(
        base=base,
        candidate=first_candidate,
        round_id="round-1",
        **review_commit_kwargs(review_boundary(base)),
    )
    second_candidate = first.snapshot.project.model_dump(mode="json")
    second_candidate["name"] = "Reviewed name"
    second = commit.commit(
        base=first.snapshot,
        candidate=second_candidate,
        round_id="round-2",
        **review_commit_kwargs(review_boundary(base, seq=3)),
    )

    # Both candidates publish live; both reviews pend; the baseline holds.
    assert second.review is not None
    current = store.read("project-1")
    assert current.generation == 2
    assert current.project.name == "Reviewed name"
    assert current.project.description == "Reviewed description"
    state = read_state(store)
    assert state.active_round_id == "round-1"
    assert state.accepted_generation == 0
    for round_id in ("round-1", "round-2"):
        assert read_review(store, round_id).status is ReviewStatus.PENDING

    edited = second.snapshot.project.model_dump(mode="json")
    edited["description"] = "User rewrote the description by hand"
    commit.commit(
        base=second.snapshot,
        candidate=edited,
        origin="frontend_edit",
        round_id="round-user-edit",
    )

    first_review = read_review(store, "round-1")
    assert first_review.status is ReviewStatus.RESOLVED
    assert [operation.decision for operation in first_review.operations] == [
        ReviewOperationDecision.SUPERSEDED_BY_USER_EDIT,
    ]
    assert read_review(store, "round-2").status is ReviewStatus.PENDING
    state = read_state(store)
    # round-2 still pends: baseline holds; pointer moves to live review.
    assert state.active_round_id == "round-2"
    assert state.accepted_generation == 0


def test_runtime_writer_rebases_pending_operation_candidate(
    tmp_path,
) -> None:
    # An auto-fix touching a reviewed pointer must rebase the pending
    # operation's candidate hash, or Keep/Undo would fail CAS forever.
    store, base = make_store(tmp_path)
    commit = ProjectCommitBoundary(store)
    reviewed = base.project.model_dump(mode="json")
    reviewed["description"] = "Reviewed description"
    first = commit.commit(
        base=base,
        candidate=reviewed,
        round_id="round-1",
        **review_commit_kwargs(review_boundary(base)),
    )

    runtime_edit = first.snapshot.project.model_dump(mode="json")
    runtime_edit["description"] = "Runtime refined description"
    commit.commit(
        base=first.snapshot,
        candidate=runtime_edit,
        origin="runtime_task",
        round_id="round-runtime-fix",
    )

    review = read_review(store, "round-1")
    assert review.status is ReviewStatus.PENDING
    (operation,) = review.operations
    assert operation.decision is ReviewOperationDecision.PENDING
    assert operation.after == "Runtime refined description"

    # Rejecting after the rebase must restore the pre-review value.
    resolved = ProjectReviewService(store).decide(
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
    assert resolved.status is ReviewStatus.RESOLVED
    assert store.read("project-1").project.description == ""


def test_transaction_completion_checks_are_disabled() -> None:
    """validate_completion is intentionally fail-open for now: both a
    coherent snapshot and one violating the atomic checks must pass."""
    from dataclasses import replace

    from services.validators.base import ValidationIssue, ValidationReport
    from services.validators.transaction import (
        CompletionSnapshot,
        validate_completion,
    )

    valid = CompletionSnapshot(
        transaction_id="tx-1",
        status="ACTIVE",
        current_working_head="head-4",
        expected_working_head="head-4",
        last_consumed_message_seq=12,
        user_message_high_water=12,
        queued_user_message_count=0,
        pending_outbox_count=0,
        specialist_run_statuses=("SUCCEEDED", "BLOCKED"),
        task_statuses=("SUCCEEDED", "QUARANTINED"),
        unimported_result_count=0,
        active_lease_count=0,
        requested_consistency_report_id="report-1",
        current_consistency_report_id="report-1",
        consistency_report_working_head="head-4",
        consistency_report_marker="SUCCESS",
        domain_reports=(ValidationReport(),),
        journal_matches_tree=True,
        seal_cas_unchanged=True,
    )
    assert validate_completion(valid).valid

    broken = replace(
        valid,
        current_working_head="head-5",
        queued_user_message_count=1,
        pending_outbox_count=1,
        task_statuses=("RUNNING",),
        active_lease_count=1,
        domain_reports=(
            ValidationReport(
                (ValidationIssue("R2V_STORYBOARD_REQUIRED", "missing"),),
            ),
        ),
        journal_matches_tree=False,
        seal_cas_unchanged=False,
    )
    assert validate_completion(broken).valid

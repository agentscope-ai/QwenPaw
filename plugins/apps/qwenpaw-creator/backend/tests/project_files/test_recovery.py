# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from domain.enums import TransactionStatus
from services.project_files import commit as commit_module
from services.project_files.commit import (
    CommitJournalState,
    PendingProjectRecoveryError,
    ProjectCommitBoundary,
    ProjectCommitJournal,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.project_files.poller import ProjectPoller
from services.project_files.recovery import (
    ProjectCommitRecoveryCoordinator,
    ProjectRecoveryIntegrityError,
    RecoveryAction,
)
from services.project_files.store import ProjectStore
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.models import (
    ChangeRoundRecord,
    ReviewBoundary,
    ReviewRecord,
    RuntimeChangeSet,
    RuntimeProjectState,
)


pytestmark = pytest.mark.unit


class SimulatedProcessDeath(RuntimeError):
    pass


def _project_store(tmp_path) -> tuple[ProjectStore, object]:
    store = ProjectStore(tmp_path.resolve())
    base = store.create(Project.new(project_id="project-1", name="Initial"))
    return store, base


def _transaction_root(store: ProjectStore, transaction_id: str):
    return (
        store.project_root("project-1")
        / "runtime"
        / "transactions"
        / transaction_id
    )


def _journal(store: ProjectStore, transaction_id: str) -> ProjectCommitJournal:
    return AtomicJsonRecordStore(
        _transaction_root(store, transaction_id) / "journal.json",
        ProjectCommitJournal,
    ).read()


def _round(store: ProjectStore, round_id: str) -> ChangeRoundRecord:
    return AtomicJsonRecordStore(
        store.project_root("project-1")
        / "runtime"
        / "change-rounds"
        / round_id
        / "round.json",
        ChangeRoundRecord,
    ).read()


def _crash_with_project_replaced(
    store: ProjectStore,
    base,
    monkeypatch,
    *,
    transaction_id: str,
    round_id: str,
    review: bool = False,
) -> None:
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Published before crash"
    boundary = None
    metadata = {}
    if review:
        boundary = ReviewBoundary(
            request_message_seq=2,
            request_id="request-2",
            interrupted_run_id="run-1",
            accepted_generation=base.generation,
            accepted_etag=base.etag,
        )
        metadata = {
            "origin": "agentdock_interrupt",
            "review_policy": "require_review",
            "review_boundary": boundary,
            "caused_by_request_id": "request-2",
            "caused_by_message_seq": 2,
        }
    else:
        metadata = {"origin": "frontend_edit"}

    boundary_service = ProjectCommitBoundary(store)
    with monkeypatch.context() as patch:
        patch.setattr(
            boundary_service,
            "_record_review",
            lambda **_kwargs: (_ for _ in ()).throw(
                SimulatedProcessDeath("crash after Project replace"),
            ),
        )
        with pytest.raises(
            SimulatedProcessDeath,
            match="after Project replace",
        ):
            boundary_service.commit(
                base=base,
                candidate=candidate,
                transaction_id=transaction_id,
                round_id=round_id,
                **metadata,
            )

    assert store.read("project-1").project.name == "Published before crash"
    assert (
        _journal(store, transaction_id).state
        is CommitJournalState.PROJECT_REPLACED
    )


def test_startup_recovery_reports_corrupt_project_without_blocking_healthy_one(
    tmp_path,
):
    store = ProjectStore(tmp_path.resolve())
    store.create(Project.new(project_id="project-good", name="Good"))
    store.create(Project.new(project_id="project-bad", name="Bad"))
    store.project_path("project-bad").write_text("{broken", encoding="utf-8")

    report = ProjectCommitRecoveryCoordinator(store).recover_all()

    assert [item.project_id for item in report.projects] == [
        "project-bad",
        "project-good",
    ]
    bad, good = report.projects
    assert not bad.ok
    assert bad.outcomes[0].action is RecoveryAction.INTEGRITY_ERROR
    assert good.ok


def test_error_after_project_replace_keeps_journal_recoverable(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    boundary = ProjectCommitBoundary(store)
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Published despite caller error"
    real_replace = store.replace

    def publish_then_raise(*args, **kwargs):
        real_replace(*args, **kwargs)
        raise OSError("injected error after atomic replacement")

    monkeypatch.setattr(store, "replace", publish_then_raise)
    with pytest.raises(OSError, match="after atomic replacement"):
        boundary.commit(
            base=base,
            candidate=candidate,
            origin="frontend_edit",
            transaction_id="post-replace-error",
        )

    journal = _journal(store, "post-replace-error")
    assert journal.state is CommitJournalState.PROJECT_REPLACED
    assert journal.publish_base_etag == base.etag
    assert journal.final_etag == store.read("project-1").etag
    monkeypatch.setattr(store, "replace", real_replace)

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )
    assert report.ok
    assert (
        _journal(store, "post-replace-error").state
        is CommitJournalState.RUNTIME_FINALIZED
    )


def test_new_commit_waits_for_unfinalized_publication_recovery(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id="crashed-commit",
        round_id="crashed-round",
    )
    current = store.read("project-1")
    next_candidate = current.project.model_dump(mode="json")
    next_candidate["description"] = "must wait"

    with pytest.raises(PendingProjectRecoveryError, match="requires recovery"):
        ProjectCommitBoundary(store).commit(
            base=current,
            candidate=next_candidate,
            origin="runtime_task",
            transaction_id="blocked-next",
        )

    ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    ).raise_for_integrity()
    result = ProjectCommitBoundary(store).commit(
        base=current,
        candidate=next_candidate,
        origin="runtime_task",
        transaction_id="after-recovery",
    )
    assert result.snapshot.project.description == "must wait"


def test_recovery_uses_prepared_latest_snapshot_for_stale_disjoint_base(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    first_candidate = base.project.model_dump(mode="json")
    first_candidate["name"] = "Concurrent name"
    first = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=first_candidate,
        origin="frontend_edit",
    )
    stale_candidate = base.project.model_dump(mode="json")
    stale_candidate["description"] = "Merged from stale base"
    boundary = ProjectCommitBoundary(store)
    with monkeypatch.context() as patch:
        patch.setattr(
            boundary,
            "_record_review",
            lambda **_kwargs: (_ for _ in ()).throw(
                SimulatedProcessDeath("crash after stale merge"),
            ),
        )
        with pytest.raises(SimulatedProcessDeath, match="stale merge"):
            boundary.commit(
                base=base,
                candidate=stale_candidate,
                origin="runtime_task",
                transaction_id="stale-merge",
                round_id="stale-merge-round",
            )

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )
    report.raise_for_integrity()
    changeset = AtomicJsonRecordStore(
        store.project_root("project-1")
        / "runtime"
        / "change-rounds"
        / "stale-merge-round"
        / "changeset.json",
        RuntimeChangeSet,
    ).read()
    current = store.read("project-1")
    assert current.project.name == "Concurrent name"
    assert current.project.description == "Merged from stale base"
    assert changeset.base_generation == first.snapshot.generation
    assert changeset.base_etag == first.snapshot.etag
    assert [change.json_pointer for change in changeset.changes] == [
        "/description",
    ]


def test_prepared_unpublished_transaction_is_aborted_safely(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-unpublished"
    round_id = "round-unpublished"
    journal_path = _transaction_root(store, transaction_id) / "journal.json"
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Never published"
    real_write = AtomicJsonRecordStore.write

    def leave_prepared(self, value):
        if (
            self.path == journal_path
            and isinstance(value, ProjectCommitJournal)
            and value.state is CommitJournalState.ABORTED
        ):
            raise SimulatedProcessDeath(
                "process died before abort journal fsync",
            )
        return real_write(self, value)

    boundary = ProjectCommitBoundary(store)
    with monkeypatch.context() as patch:
        patch.setattr(
            store,
            "replace",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                SimulatedProcessDeath("process died before Project publish"),
            ),
        )
        patch.setattr(AtomicJsonRecordStore, "write", leave_prepared)
        with pytest.raises(SimulatedProcessDeath, match="abort journal"):
            boundary.commit(
                base=base,
                candidate=candidate,
                origin="frontend_edit",
                transaction_id=transaction_id,
                round_id=round_id,
            )

    assert store.read("project-1").etag == base.etag
    assert _journal(store, transaction_id).state is CommitJournalState.PREPARED
    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )

    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.ABORTED_UNPUBLISHED
    assert _journal(store, transaction_id).state is CommitJournalState.ABORTED
    assert _round(store, round_id).status is TransactionStatus.ABORTED
    assert store.read("project-1").etag == base.etag


def test_prepared_but_published_project_is_proved_and_fully_recovered(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-prepared-published"
    round_id = "round-custom"
    journal_path = _transaction_root(store, transaction_id) / "journal.json"
    candidate = base.project.model_dump(mode="json")
    candidate["description"] = "published in the narrow crash window"
    real_write = AtomicJsonRecordStore.write

    def crash_before_journal_transition(self, value):
        if (
            self.path == journal_path
            and isinstance(value, ProjectCommitJournal)
            and value.state is not CommitJournalState.PREPARED
        ):
            raise SimulatedProcessDeath("journal transition was not durable")
        return real_write(self, value)

    with monkeypatch.context() as patch:
        patch.setattr(
            AtomicJsonRecordStore,
            "write",
            crash_before_journal_transition,
        )
        with pytest.raises(SimulatedProcessDeath, match="journal transition"):
            ProjectCommitBoundary(store).commit(
                base=base,
                candidate=candidate,
                origin="frontend_edit",
                transaction_id=transaction_id,
                round_id=round_id,
            )

    current = store.read("project-1")
    assert (
        current.project.description == "published in the narrow crash window"
    )
    assert _journal(store, transaction_id).state is CommitJournalState.PREPARED

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )
    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.FINALIZED_RUNTIME
    assert (
        _journal(store, transaction_id).state
        is CommitJournalState.RUNTIME_FINALIZED
    )
    changeset = AtomicJsonRecordStore(
        store.project_root("project-1")
        / "runtime"
        / "change-rounds"
        / round_id
        / "changeset.json",
        RuntimeChangeSet,
    ).read()
    assert [change.json_pointer for change in changeset.changes] == [
        "/description",
    ]
    assert changeset.base_etag == base.etag
    assert changeset.final_etag == current.etag


def test_project_replaced_recovery_is_idempotent_and_rebuilds_runtime_state(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-project-replaced"
    round_id = "round-project-replaced"
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id=transaction_id,
        round_id=round_id,
    )

    coordinator = ProjectCommitRecoveryCoordinator(store)
    first = coordinator.recover_project("project-1")
    second = coordinator.recover_project("project-1")
    current = store.read("project-1")

    assert first.outcomes[0].action is RecoveryAction.FINALIZED_RUNTIME
    assert second.outcomes[0].action is RecoveryAction.ALREADY_FINALIZED
    state = AtomicJsonRecordStore(
        store.project_root("project-1") / "runtime" / "state.json",
        RuntimeProjectState,
    ).read()
    assert state.last_project_generation == current.generation
    assert state.last_project_etag == current.etag
    assert state.accepted_generation == current.generation
    assert _round(store, round_id).status is TransactionStatus.COMMITTED


def test_restart_facade_runs_recovery_once_and_exposes_report(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-restart"
    round_id = "round-restart"
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id=transaction_id,
        round_id=round_id,
    )

    restarted = CreatorFileServices.create(tmp_path.resolve())

    assert restarted.startup_recovery.ok
    assert restarted.startup_recovery.projects[0].outcomes[0].action is (
        RecoveryAction.FINALIZED_RUNTIME
    )
    assert (
        _journal(store, transaction_id).state
        is CommitJournalState.RUNTIME_FINALIZED
    )
    assert restarted.recover_project("project-1").outcomes[0].action is (
        RecoveryAction.ALREADY_FINALIZED
    )


def test_startup_accepts_finalized_disjoint_merge_with_newer_published_base(
    tmp_path,
):
    store, original = _project_store(tmp_path)
    first = original.project.model_dump(mode="json")
    first["name"] = "First"
    first_result = ProjectCommitBoundary(store).commit(
        base=original,
        candidate=first,
        origin="frontend_edit",
        transaction_id="tx-disjoint-first",
    )
    second = original.project.model_dump(mode="json")
    second["description"] = "Second"
    second_result = ProjectCommitBoundary(store).commit(
        base=original,
        candidate=second,
        origin="runtime_task",
        transaction_id="tx-disjoint-second",
    )
    second_changeset = AtomicJsonRecordStore(
        store.project_root("project-1")
        / "runtime"
        / "change-rounds"
        / "tx-disjoint-second"
        / "changeset.json",
        RuntimeChangeSet,
    ).read()

    report = ProjectCommitRecoveryCoordinator(store).recover_all()

    assert report.ok
    assert all(
        outcome.action is RecoveryAction.ALREADY_FINALIZED
        for outcome in report.projects[0].outcomes
    )
    assert second_changeset.base_etag == first_result.snapshot.etag
    assert second_changeset.base_etag != original.etag
    assert store.read("project-1") == second_result.snapshot


def test_recovery_recreates_pending_review_from_durable_boundary(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-review"
    round_id = "round-review"
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id=transaction_id,
        round_id=round_id,
        review=True,
    )

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )
    current = store.read("project-1")
    review = AtomicJsonRecordStore(
        store.project_root("project-1")
        / "runtime"
        / "reviews"
        / f"review-{round_id}"
        / "review.json",
        ReviewRecord,
    ).read()
    state = AtomicJsonRecordStore(
        store.project_root("project-1") / "runtime" / "state.json",
        RuntimeProjectState,
    ).read()

    assert report.ok
    assert review.request_id == "request-2"
    assert review.candidate_etag == current.etag
    assert [operation.json_pointer for operation in review.operations] == [
        "/name",
    ]
    assert state.active_round_id == round_id
    assert state.accepted_generation == base.generation
    assert _round(store, round_id).status is TransactionStatus.PENDING_REVIEW


def test_recovery_clears_state_when_frontend_already_resolved_review(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    review_candidate = base.project.model_dump(mode="json")
    review_candidate["name"] = "Agent candidate"
    boundary = ReviewBoundary(
        request_message_seq=2,
        request_id="request-2",
        interrupted_run_id="run-1",
        accepted_generation=base.generation,
        accepted_etag=base.etag,
    )
    pending = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=review_candidate,
        origin="agentdock_interrupt",
        review_policy="require_review",
        review_boundary=boundary,
        caused_by_request_id="request-2",
        caused_by_message_seq=2,
        transaction_id="tx-review-candidate",
        round_id="round-review-candidate",
    )
    current = pending.snapshot
    user_candidate = current.project.model_dump(mode="json")
    user_candidate["name"] = "User value"
    frontend = ProjectCommitBoundary(store)

    with monkeypatch.context() as patch:
        patch.setattr(
            frontend,
            "_update_runtime_state",
            lambda **_kwargs: (_ for _ in ()).throw(
                SimulatedProcessDeath("state write did not happen"),
            ),
        )
        with pytest.raises(SimulatedProcessDeath, match="state write"):
            frontend.commit(
                base=current,
                candidate=user_candidate,
                origin="frontend_edit",
                transaction_id="tx-user-supersede",
                round_id="round-user-supersede",
            )

    review = AtomicJsonRecordStore(
        store.project_root("project-1")
        / "runtime"
        / "reviews"
        / "review-round-review-candidate"
        / "review.json",
        ReviewRecord,
    ).read()
    stale_state = AtomicJsonRecordStore(
        store.project_root("project-1") / "runtime" / "state.json",
        RuntimeProjectState,
    ).read()
    assert review.status.value == "RESOLVED"
    assert stale_state.active_round_id == "round-review-candidate"

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )
    recovered = AtomicJsonRecordStore(
        store.project_root("project-1") / "runtime" / "state.json",
        RuntimeProjectState,
    ).read()
    assert report.ok
    assert recovered.active_round_id is None
    assert recovered.accepted_generation == store.read("project-1").generation


def test_finalized_review_may_legitimately_advance_with_a_later_project_commit(
    tmp_path,
):
    store, base = _project_store(tmp_path)
    boundary = ReviewBoundary(
        request_message_seq=2,
        request_id="request-review-advance",
        interrupted_run_id="run-review-advance",
        accepted_generation=base.generation,
        accepted_etag=base.etag,
    )
    reviewed_candidate = base.project.model_dump(mode="json")
    reviewed_candidate["name"] = "Needs review"
    reviewed = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=reviewed_candidate,
        origin="agentdock_interrupt",
        review_policy="require_review",
        review_boundary=boundary,
        caused_by_request_id=boundary.request_id,
        caused_by_message_seq=boundary.request_message_seq,
        transaction_id="tx-review-advance",
        round_id="round-review-advance",
    )
    later_candidate = reviewed.snapshot.project.model_dump(mode="json")
    later_candidate["description"] = "Unrelated accepted frontend edit"
    later = ProjectCommitBoundary(store).commit(
        base=reviewed.snapshot,
        candidate=later_candidate,
        origin="frontend_edit",
        transaction_id="tx-after-review",
    )
    review = AtomicJsonRecordStore(
        store.project_root("project-1")
        / "runtime"
        / "reviews"
        / "review-round-review-advance"
        / "review.json",
        ReviewRecord,
    ).read()

    report = ProjectCommitRecoveryCoordinator(store).recover_all()

    assert review.candidate_generation == later.snapshot.generation
    assert review.candidate_etag == later.snapshot.etag
    assert report.ok
    assert all(
        outcome.action is RecoveryAction.ALREADY_FINALIZED
        for outcome in report.projects[0].outcomes
    )


def test_finalized_journal_repairs_missing_runtime_records(tmp_path):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-finalized-repair"
    round_id = "round-finalized-repair"
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Committed"
    ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
        transaction_id=transaction_id,
        round_id=round_id,
    )
    runtime_root = store.project_root("project-1") / "runtime"
    (runtime_root / "change-rounds" / round_id / "changeset.json").unlink()
    (runtime_root / "state.json").unlink()
    round_store = AtomicJsonRecordStore(
        runtime_root / "change-rounds" / round_id / "round.json",
        ChangeRoundRecord,
    )
    round_record = round_store.read()
    round_store.write(
        round_record.model_copy(update={"status": TransactionStatus.ACTIVE}),
    )

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )

    assert (
        report.outcomes[0].action is RecoveryAction.REPAIRED_FINALIZED_RUNTIME
    )
    assert (
        AtomicJsonRecordStore(
            runtime_root / "change-rounds" / round_id / "changeset.json",
            RuntimeChangeSet,
        )
        .read()
        .final_etag
        == store.read("project-1").etag
    )
    assert (
        AtomicJsonRecordStore(runtime_root / "state.json", RuntimeProjectState)
        .read()
        .last_project_etag
        == store.read("project-1").etag
    )
    assert _round(store, round_id).status is TransactionStatus.COMMITTED


def test_finalized_no_change_journal_can_rebuild_its_runtime_records(tmp_path):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-no-change-repair"
    round_id = "round-no-change-repair"
    ProjectCommitBoundary(store).commit(
        base=base,
        candidate=base.project.model_dump(mode="json"),
        origin="frontend_edit",
        transaction_id=transaction_id,
        round_id=round_id,
    )
    runtime_root = store.project_root("project-1") / "runtime"
    (runtime_root / "change-rounds" / round_id / "changeset.json").unlink()
    (runtime_root / "state.json").unlink()

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )
    changeset = AtomicJsonRecordStore(
        runtime_root / "change-rounds" / round_id / "changeset.json",
        RuntimeChangeSet,
    ).read()

    assert (
        report.outcomes[0].action is RecoveryAction.REPAIRED_FINALIZED_RUNTIME
    )
    assert changeset.changes == []
    assert changeset.base_etag == changeset.final_etag == base.etag
    assert _round(store, round_id).status is TransactionStatus.NO_CHANGE


def test_prepared_no_change_crash_recovers_runtime_without_rewriting_project(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-no-change-crash"
    target = (
        store.project_root("project-1")
        / "runtime"
        / "transactions"
        / transaction_id
        / "changeset.json"
    )
    original_create = AtomicJsonRecordStore.create
    failed = False

    def fail_transaction_changeset_once(self, value):
        nonlocal failed
        if self.path == target and not failed:
            failed = True
            raise RuntimeError("injected no-change Runtime crash")
        return original_create(self, value)

    monkeypatch.setattr(
        AtomicJsonRecordStore,
        "create",
        fail_transaction_changeset_once,
    )
    with pytest.raises(RuntimeError, match="no-change Runtime crash"):
        ProjectCommitBoundary(store).commit(
            base=base,
            candidate=base.project.model_dump(mode="json"),
            origin="runtime_task",
            transaction_id=transaction_id,
            round_id="round-no-change-crash",
        )

    assert store.read("project-1") == base
    journal_store = AtomicJsonRecordStore(
        target.parent / "journal.json",
        ProjectCommitJournal,
    )
    assert journal_store.read().state is CommitJournalState.PREPARED

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )

    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.FINALIZED_RUNTIME
    assert journal_store.read().state is CommitJournalState.RUNTIME_FINALIZED
    assert AtomicJsonRecordStore(target, RuntimeChangeSet).read().changes == []
    assert (
        _round(store, "round-no-change-crash").status
        is TransactionStatus.NO_CHANGE
    )


def test_recovery_recreates_aggregate_after_transaction_publish_crash(
    tmp_path,
    monkeypatch,
) -> None:
    store, base = _project_store(tmp_path)
    transaction_id = "tx-before-aggregate"
    round_id = "round-before-aggregate"
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Not published"
    transactions_root = (
        store.project_root("project-1") / "runtime" / "transactions"
    )
    aggregate_path = (
        store.project_root("project-1")
        / "runtime"
        / "change-rounds"
        / round_id
        / "round.json"
    )
    original_fsync_directory = commit_module.fsync_directory
    failed = False

    def fail_after_transaction_rename(path):
        nonlocal failed
        if Path(path) == transactions_root and not failed:
            failed = True
            raise SimulatedProcessDeath("crash before aggregate projection")
        return original_fsync_directory(path)

    with monkeypatch.context() as patch:
        patch.setattr(
            commit_module,
            "fsync_directory",
            fail_after_transaction_rename,
        )
        with pytest.raises(SimulatedProcessDeath, match="before aggregate"):
            ProjectCommitBoundary(store).commit(
                base=base,
                candidate=candidate,
                origin="runtime_task",
                transaction_id=transaction_id,
                round_id=round_id,
            )

    assert (
        _transaction_root(store, transaction_id) / "journal.json"
    ).is_file()
    assert not aggregate_path.exists()

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )

    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.ABORTED_UNPUBLISHED
    assert _journal(store, transaction_id).state is CommitJournalState.ABORTED
    assert _round(store, round_id).status is TransactionStatus.ABORTED
    assert store.read("project-1") == base


def test_recovery_aborts_dangling_publish_snapshots_before_journal_update(
    tmp_path,
    monkeypatch,
) -> None:
    store, base = _project_store(tmp_path)
    transaction_id = "tx-dangling-publish-snapshots"
    round_id = "round-dangling-publish-snapshots"
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Not published"
    transaction_root = _transaction_root(store, transaction_id)

    with monkeypatch.context() as patch:
        patch.setattr(
            store,
            "replace",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected failure before Project publish"),
            ),
        )
        with pytest.raises(RuntimeError, match="before Project publish"):
            ProjectCommitBoundary(store).commit(
                base=base,
                candidate=candidate,
                origin="runtime_task",
                transaction_id=transaction_id,
                round_id=round_id,
            )

    assert (transaction_root / "latest.json").is_file()
    assert (transaction_root / "final.json").is_file()
    journal_store = AtomicJsonRecordStore(
        transaction_root / "journal.json",
        ProjectCommitJournal,
    )
    journal = journal_store.read()
    journal_store.write(
        journal.model_copy(
            update={
                "state": CommitJournalState.PREPARED,
                "publish_base_etag": None,
                "final_etag": None,
                "error": None,
            },
        ),
    )
    transaction_round_store = AtomicJsonRecordStore(
        transaction_root / "round.json",
        ChangeRoundRecord,
    )
    transaction_round = transaction_round_store.read()
    transaction_round_store.write(
        transaction_round.model_copy(
            update={"status": TransactionStatus.ACTIVE},
        ),
    )
    aggregate_store = AtomicJsonRecordStore(
        store.project_root("project-1")
        / "runtime"
        / "change-rounds"
        / round_id
        / "round.json",
        ChangeRoundRecord,
    )
    aggregate_round = aggregate_store.read()
    aggregate_store.write(
        aggregate_round.model_copy(
            update={"status": TransactionStatus.ACTIVE},
        ),
    )

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )

    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.ABORTED_UNPUBLISHED
    assert journal_store.read().state is CommitJournalState.ABORTED
    assert store.read("project-1") == base


def test_etag_mismatch_is_reported_without_overwriting_current_or_last_good(
    tmp_path,
    monkeypatch,
):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-etag-mismatch"
    round_id = "round-etag-mismatch"
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id=transaction_id,
        round_id=round_id,
    )
    published = store.read("project-1")
    raw = published.project.model_dump(mode="python")
    raw["generation"] += 1
    raw["description"] = "newer unrelated current"
    raw["updated_at"] = raw["updated_at"] + timedelta(seconds=1)
    newer = store.replace(
        "project-1",
        Project.model_validate(raw),
        expected_etag=published.etag,
    )
    poller = ProjectPoller(store)
    last_good = poller.open("project-1")

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )

    assert not report.ok
    assert report.outcomes[0].action is RecoveryAction.INTEGRITY_ERROR
    assert "ETag" in (report.outcomes[0].detail or "")
    assert store.read("project-1") == newer
    assert poller.cached("project-1") == last_good
    assert (
        _journal(store, transaction_id).state
        is CommitJournalState.PROJECT_REPLACED
    )
    with pytest.raises(ProjectRecoveryIntegrityError):
        report.raise_for_integrity()


def test_corrupt_journal_reports_integrity_and_preserves_project(tmp_path):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-corrupt"
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Committed"
    result = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
        transaction_id=transaction_id,
    )
    poller = ProjectPoller(store)
    last_good = poller.open("project-1")
    journal_path = _transaction_root(store, transaction_id) / "journal.json"
    journal_path.write_text("{broken", encoding="utf-8")

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )

    assert not report.ok
    assert report.outcomes[0].action is RecoveryAction.INTEGRITY_ERROR
    assert store.read("project-1") == result.snapshot
    assert poller.cached("project-1") == last_good


def test_legacy_journal_is_parseable_but_never_guessed(tmp_path):
    store, base = _project_store(tmp_path)
    transaction_id = "tx-legacy"
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Committed"
    result = ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
        transaction_id=transaction_id,
    )
    journal_path = _transaction_root(store, transaction_id) / "journal.json"
    raw = json.loads(journal_path.read_text(encoding="utf-8"))
    raw.pop("round_id")
    raw.pop("advance_accepted_baseline")
    journal_path.write_text(json.dumps(raw), encoding="utf-8")

    parsed = AtomicJsonRecordStore(
        journal_path,
        ProjectCommitJournal,
    ).read()
    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )

    assert parsed.round_id is None
    assert parsed.advance_accepted_baseline is None
    assert report.outcomes[0].action is RecoveryAction.INTEGRITY_ERROR
    assert "legacy journal" in (report.outcomes[0].detail or "")
    assert store.read("project-1") == result.snapshot


def test_legacy_schema_replaced_transaction_is_finalized_not_fail_closed(
    tmp_path,
    monkeypatch,
):
    """A pre-migration PROJECT_REPLACED transaction must not fail-close the
    Project after a schema upgrade: recovery advances its journal so the
    commit-time pending-publication guard accepts new writes again."""

    store, base = _project_store(tmp_path)
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id="legacy-replaced",
        round_id="round-legacy",
    )
    base_store = AtomicJsonRecordStore(
        _transaction_root(store, "legacy-replaced") / "base.json",
    )
    base_data = base_store.read()
    base_data["schema_version"] = 999
    base_store.write(base_data)

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )
    assert report.ok
    outcome = next(
        item
        for item in report.outcomes
        if item.transaction_id == "legacy-replaced"
    )
    assert outcome.action is RecoveryAction.ALREADY_FINALIZED
    assert "legacy-schema" in (outcome.detail or "")
    assert (
        _journal(store, "legacy-replaced").state
        is CommitJournalState.RUNTIME_FINALIZED
    )

    # New commits pass the pending-publication guard again.
    current = store.read("project-1")
    candidate = current.project.model_dump(mode="json")
    candidate["name"] = "After legacy recovery"
    ProjectCommitBoundary(store).commit(
        base=current,
        candidate=candidate,
        origin="frontend_edit",
        transaction_id="post-legacy-commit",
    )
    assert store.read("project-1").project.name == "After legacy recovery"


def test_legacy_schema_aborted_transaction_is_skipped(tmp_path, monkeypatch):
    store, base = _project_store(tmp_path)
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id="legacy-aborted",
        round_id="round-legacy-aborted",
    )
    journal_store = AtomicJsonRecordStore(
        _transaction_root(store, "legacy-aborted") / "journal.json",
        ProjectCommitJournal,
    )
    snapshot = journal_store.read_snapshot()
    journal_store.compare_and_swap(
        expected_checksum=snapshot.checksum,
        value=snapshot.value.model_copy(
            update={"state": CommitJournalState.ABORTED},
        ),
    )
    base_store = AtomicJsonRecordStore(
        _transaction_root(store, "legacy-aborted") / "base.json",
    )
    base_data = base_store.read()
    base_data["schema_version"] = 999
    base_store.write(base_data)

    report = ProjectCommitRecoveryCoordinator(store).recover_project(
        "project-1",
    )
    assert report.ok
    outcome = next(
        item
        for item in report.outcomes
        if item.transaction_id == "legacy-aborted"
    )
    assert outcome.action is RecoveryAction.SKIPPED_ABORTED
    assert "legacy-schema" in (outcome.detail or "")
    assert (
        _journal(store, "legacy-aborted").state is CommitJournalState.ABORTED
    )

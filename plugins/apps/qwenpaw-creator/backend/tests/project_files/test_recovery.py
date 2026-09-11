# -*- coding: utf-8 -*-
from __future__ import annotations

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
from services.project_files.models import Project
from services.project_files.poller import ProjectPoller
from services.project_files.recovery import (
    ProjectCommitRecoveryCoordinator,
    ProjectRecoveryIntegrityError,
    RecoveryAction,
)
from services.project_files.store import ProjectStore
from services.runtime_files.atomic_store import AtomicJsonRecordStore

from .conftest import (
    make_store,
    read_changeset,
    read_journal,
    read_review,
    read_round,
    read_state,
    recover,
    review_boundary,
    review_commit_kwargs,
    round_store,
    runtime_root,
    transaction_root,
)


pytestmark = pytest.mark.unit


class SimulatedProcessDeath(RuntimeError):
    pass


def _crash_with_project_replaced(
    store,
    base,
    monkeypatch,
    *,
    transaction_id,
    round_id,
    review=False,
):
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Published before crash"
    if review:
        metadata = review_commit_kwargs(review_boundary(base))
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
        read_journal(store, transaction_id).state
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


def test_new_commit_waits_for_unfinalized_publication_recovery(
    tmp_path,
    monkeypatch,
):
    store, base = make_store(tmp_path)
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

    recover(store).raise_for_integrity()
    result = ProjectCommitBoundary(store).commit(
        base=current,
        candidate=next_candidate,
        origin="runtime_task",
        transaction_id="after-recovery",
    )
    assert result.snapshot.project.description == "must wait"


def test_prepared_unpublished_transaction_is_aborted_safely(
    tmp_path,
    monkeypatch,
):
    store, base = make_store(tmp_path)
    transaction_id = "tx-unpublished"
    round_id = "round-unpublished"
    journal_path = transaction_root(store, transaction_id) / "journal.json"
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
    assert (
        read_journal(store, transaction_id).state
        is CommitJournalState.PREPARED
    )
    report = recover(store)

    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.ABORTED_UNPUBLISHED
    assert (
        read_journal(store, transaction_id).state is CommitJournalState.ABORTED
    )
    assert read_round(store, round_id).status is TransactionStatus.ABORTED
    assert store.read("project-1").etag == base.etag


def test_prepared_but_published_project_is_proved_and_fully_recovered(
    tmp_path,
    monkeypatch,
):
    store, base = make_store(tmp_path)
    transaction_id = "tx-prepared-published"
    round_id = "round-custom"
    journal_path = transaction_root(store, transaction_id) / "journal.json"
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
    assert (
        read_journal(store, transaction_id).state
        is CommitJournalState.PREPARED
    )

    report = recover(store)
    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.FINALIZED_RUNTIME
    assert (
        read_journal(store, transaction_id).state
        is CommitJournalState.RUNTIME_FINALIZED
    )
    changeset = read_changeset(store, round_id)
    assert [c.json_pointer for c in changeset.changes] == ["/description"]
    assert changeset.base_etag == base.etag
    assert changeset.final_etag == current.etag


def test_project_replaced_recovery_is_idempotent_and_rebuilds_runtime_state(
    tmp_path,
    monkeypatch,
):
    store, base = make_store(tmp_path)
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
    state = read_state(store)
    assert state.last_project_generation == current.generation
    assert state.last_project_etag == current.etag
    assert state.accepted_generation == current.generation
    assert read_round(store, round_id).status is TransactionStatus.COMMITTED


def test_recovery_recreates_pending_review_from_durable_boundary(
    tmp_path,
    monkeypatch,
):
    store, base = make_store(tmp_path)
    round_id = "round-review"
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id="tx-review",
        round_id=round_id,
        review=True,
    )

    report = recover(store)
    current = store.read("project-1")
    review = read_review(store, round_id)
    state = read_state(store)

    assert report.ok
    assert review.request_id == "request-2"
    assert review.candidate_etag == current.etag
    assert [o.json_pointer for o in review.operations] == ["/name"]
    assert state.active_round_id == round_id
    assert state.accepted_generation == base.generation
    assert (
        read_round(store, round_id).status is TransactionStatus.PENDING_REVIEW
    )


def test_finalized_journal_repairs_missing_runtime_records(tmp_path):
    store, base = make_store(tmp_path)
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
    rt_root = runtime_root(store)
    (rt_root / "change-rounds" / round_id / "changeset.json").unlink()
    (rt_root / "state.json").unlink()
    rounds = round_store(store, round_id)
    rounds.write(
        rounds.read().model_copy(update={"status": TransactionStatus.ACTIVE}),
    )

    report = recover(store)

    assert (
        report.outcomes[0].action is RecoveryAction.REPAIRED_FINALIZED_RUNTIME
    )
    assert (
        read_changeset(store, round_id).final_etag
        == store.read("project-1").etag
    )
    assert read_state(store).last_project_etag == store.read("project-1").etag
    assert read_round(store, round_id).status is TransactionStatus.COMMITTED


def test_recovery_recreates_aggregate_after_transaction_publish_crash(
    tmp_path,
    monkeypatch,
) -> None:
    store, base = make_store(tmp_path)
    transaction_id = "tx-before-aggregate"
    round_id = "round-before-aggregate"
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Not published"
    transactions_root = runtime_root(store) / "transactions"
    aggregate_path = (
        runtime_root(store) / "change-rounds" / round_id / "round.json"
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

    assert (transaction_root(store, transaction_id) / "journal.json").is_file()
    assert not aggregate_path.exists()

    report = recover(store)

    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.ABORTED_UNPUBLISHED
    assert (
        read_journal(store, transaction_id).state is CommitJournalState.ABORTED
    )
    assert read_round(store, round_id).status is TransactionStatus.ABORTED
    assert store.read("project-1") == base


def test_etag_mismatch_is_reported_without_overwriting_current_or_last_good(
    tmp_path,
    monkeypatch,
):
    store, base = make_store(tmp_path)
    transaction_id = "tx-etag-mismatch"
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id=transaction_id,
        round_id="round-etag-mismatch",
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

    report = recover(store)

    assert not report.ok
    assert report.outcomes[0].action is RecoveryAction.INTEGRITY_ERROR
    assert "ETag" in (report.outcomes[0].detail or "")
    assert store.read("project-1") == newer
    assert poller.cached("project-1") == last_good
    assert (
        read_journal(store, transaction_id).state
        is CommitJournalState.PROJECT_REPLACED
    )
    with pytest.raises(ProjectRecoveryIntegrityError):
        report.raise_for_integrity()


def test_legacy_schema_transaction_recovers_without_fail_closing(
    tmp_path,
    monkeypatch,
):
    """A pre-migration PROJECT_REPLACED transaction must not fail-close the
    Project after a schema upgrade: recovery advances its journal so the
    commit-time pending-publication guard accepts new writes again."""

    store, base = make_store(tmp_path)
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id="legacy-tx",
        round_id="round-legacy",
    )
    base_store = AtomicJsonRecordStore(
        transaction_root(store, "legacy-tx") / "base.json",
    )
    base_data = base_store.read()
    base_data["schema_version"] = 999
    base_store.write(base_data)

    report = recover(store)
    assert report.ok
    outcome = next(
        item for item in report.outcomes if item.transaction_id == "legacy-tx"
    )
    assert outcome.action is RecoveryAction.ALREADY_FINALIZED
    assert "frozen-model" in (outcome.detail or "")
    assert (
        read_journal(store, "legacy-tx").state
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

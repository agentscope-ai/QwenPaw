# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-boolean-expressions,too-many-branches
# pylint: disable=too-many-return-statements,too-many-statements
"""Idempotent startup recovery for Project commit journals.

Recovery never rewrites ``project.json``.  It may only complete Runtime facts
when the transaction snapshots, journal and current Project prove one unique
outcome.  Ambiguous or corrupt input is reported and left in place so the
poller's last-good Project snapshot remains untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
import secrets
import stat
from typing import Any, TypeVar

from domain.enums import TransactionStatus
from services.runtime_files.atomic_store import (
    AtomicJsonRecordStore,
    RecordSnapshot,
)
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.models import (
    ChangeOrigin,
    ChangeRoundRecord,
    ProjectChange,
    ReviewOperation,
    ReviewOperationDecision,
    ReviewPolicy,
    ReviewRecord,
    ReviewStatus,
    RuntimeChangeSet,
    RuntimeProjectState,
    SyncStatus,
)

from .commit import (
    CommitJournalState,
    ProjectCommitJournal,
    _candidate_hash,
    _review_operation_id,
    _runtime_change,
    _update_manual_edit_buffer,
    _validate_same_round,
    is_protected_pointer,
)
from .json_pointer import JsonChange, diff_json, pointers_overlap
from .models import Project
from .serialization import project_etag
from .store import ProjectSnapshot, ProjectStore


class RecoveryAction(StrEnum):
    ABORTED_UNPUBLISHED = "aborted_unpublished"
    FINALIZED_RUNTIME = "finalized_runtime"
    REPAIRED_FINALIZED_RUNTIME = "repaired_finalized_runtime"
    ALREADY_FINALIZED = "already_finalized"
    SKIPPED_ABORTED = "skipped_aborted"
    INTEGRITY_ERROR = "integrity_error"


@dataclass(frozen=True, slots=True)
class TransactionRecoveryOutcome:
    transaction_id: str
    action: RecoveryAction
    state_before: CommitJournalState | None
    state_after: CommitJournalState | None
    detail: str | None = None

    @property
    def integrity_error(self) -> bool:
        return self.action is RecoveryAction.INTEGRITY_ERROR


@dataclass(frozen=True, slots=True)
class ProjectRecoveryReport:
    project_id: str
    outcomes: tuple[TransactionRecoveryOutcome, ...]

    @property
    def integrity_errors(self) -> tuple[TransactionRecoveryOutcome, ...]:
        return tuple(item for item in self.outcomes if item.integrity_error)

    @property
    def ok(self) -> bool:
        return not self.integrity_errors

    def raise_for_integrity(self) -> None:
        if self.integrity_errors:
            raise ProjectRecoveryIntegrityError(self)


@dataclass(frozen=True, slots=True)
class CreatorRecoveryReport:
    projects: tuple[ProjectRecoveryReport, ...]

    @property
    def integrity_errors(self) -> tuple[TransactionRecoveryOutcome, ...]:
        return tuple(
            outcome
            for project in self.projects
            for outcome in project.integrity_errors
        )

    @property
    def ok(self) -> bool:
        return not self.integrity_errors


class ProjectRecoveryIntegrityError(RuntimeError):
    def __init__(self, report: ProjectRecoveryReport) -> None:
        self.report = report
        details = "; ".join(
            f"{item.transaction_id}: {item.detail or 'integrity error'}"
            for item in report.integrity_errors
        )
        super().__init__(f"Project commit recovery failed: {details}")


class _IntegrityProblem(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _RecoveryInputs:
    journal: ProjectCommitJournal
    journal_checksum: str
    journal_store: AtomicJsonRecordStore[ProjectCommitJournal]
    transaction_root: Path
    base_data: dict[str, Any]
    base_project: Project
    candidate_data: dict[str, Any]
    latest_data: dict[str, Any] | None
    latest_project: Project | None
    final_data: dict[str, Any] | None
    final_project: Project | None
    round_record: ChangeRoundRecord
    round_checksum: str
    round_store: AtomicJsonRecordStore[ChangeRoundRecord]
    aggregate_round_checksum: str
    aggregate_round_store: AtomicJsonRecordStore[ChangeRoundRecord]


@dataclass(frozen=True, slots=True)
class _ExistingReviewUpdate:
    store: AtomicJsonRecordStore[ReviewRecord]
    checksum: str
    value: ReviewRecord
    pending: bool


@dataclass(frozen=True, slots=True)
class _NewReviewPlan:
    store: AtomicJsonRecordStore[ReviewRecord]
    existing: RecordSnapshot[ReviewRecord] | None
    value: ReviewRecord


T = TypeVar("T")


class ProjectCommitRecoveryCoordinator:
    """Scan and reconcile commit journals below one Project Runtime."""

    def __init__(
        self,
        store: ProjectStore,
        *,
        lock_timeout_seconds: float = 10.0,
    ) -> None:
        self.store = store
        self.lock_timeout_seconds = lock_timeout_seconds

    def recover_project(
        self,
        project_id: str,
        *,
        _lifecycle_lock_held: bool = False,
    ) -> ProjectRecoveryReport:
        if _lifecycle_lock_held:
            return self._recover_project_lifecycle_locked(project_id)
        with self.store.lifecycle_lock(project_id):
            return self._recover_project_lifecycle_locked(project_id)

    def _recover_project_lifecycle_locked(
        self,
        project_id: str,
    ) -> ProjectRecoveryReport:
        # Resolve through ProjectStore so project_id/path containment and the
        # current authority file are validated before touching Runtime facts.
        self.store.read(project_id)
        runtime_root = self.store.project_root(project_id) / "runtime"
        transactions_root = runtime_root / "transactions"
        if not transactions_root.exists():
            return ProjectRecoveryReport(project_id=project_id, outcomes=())
        if transactions_root.is_symlink() or not transactions_root.is_dir():
            outcome = TransactionRecoveryOutcome(
                transaction_id="<transactions-root>",
                action=RecoveryAction.INTEGRITY_ERROR,
                state_before=None,
                state_after=None,
                detail="runtime/transactions must be a real directory",
            )
            return ProjectRecoveryReport(
                project_id=project_id,
                outcomes=(outcome,),
            )

        with (
            CrossProcessFileLock(
                runtime_root / "locks" / "project-commit-order.lock",
                timeout_seconds=self.lock_timeout_seconds,
            ),
            CrossProcessFileLock(
                runtime_root / "locks" / "project-recovery.lock",
                timeout_seconds=self.lock_timeout_seconds,
            ),
            CrossProcessFileLock(
                runtime_root / "locks" / "project-write.lock",
                timeout_seconds=self.lock_timeout_seconds,
            ),
        ):
            outcomes = tuple(
                self._recover_entry(project_id, runtime_root, entry)
                for entry in sorted(
                    transactions_root.iterdir(),
                    key=lambda item: item.name,
                )
                if not entry.name.startswith(".")
            )
        return ProjectRecoveryReport(project_id=project_id, outcomes=outcomes)

    def recover_all(self) -> CreatorRecoveryReport:
        """Recover every discoverable Project without one bad Project halting boot."""

        reports: list[ProjectRecoveryReport] = []
        for project_id in self.store.discover_project_ids():
            try:
                reports.append(self.recover_project(project_id))
            except Exception as exc:
                reports.append(
                    ProjectRecoveryReport(
                        project_id=project_id,
                        outcomes=(
                            TransactionRecoveryOutcome(
                                transaction_id="<project>",
                                action=RecoveryAction.INTEGRITY_ERROR,
                                state_before=None,
                                state_after=None,
                                detail=f"{type(exc).__name__}: {exc}",
                            ),
                        ),
                    ),
                )
        return CreatorRecoveryReport(projects=tuple(reports))

    def _recover_entry(
        self,
        project_id: str,
        runtime_root: Path,
        transaction_root: Path,
    ) -> TransactionRecoveryOutcome:
        transaction_id = transaction_root.name
        state_before: CommitJournalState | None = None
        try:
            entry_stat = transaction_root.lstat()
            if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(
                entry_stat.st_mode,
            ):
                raise _IntegrityProblem(
                    "transaction entry must be a real directory",
                )
            journal_path = transaction_root / "journal.json"
            try:
                journal_stat = journal_path.lstat()
            except FileNotFoundError as exc:
                raise _IntegrityProblem(
                    "transaction directory has no journal.json",
                ) from exc
            if stat.S_ISLNK(journal_stat.st_mode) or not stat.S_ISREG(
                journal_stat.st_mode,
            ):
                raise _IntegrityProblem(
                    "journal.json must be a regular non-symlink file",
                )

            inputs = self._load_inputs(
                project_id,
                runtime_root,
                transaction_root,
            )
            transaction_id = inputs.journal.transaction_id
            state_before = inputs.journal.state
            if state_before is CommitJournalState.ABORTED:
                return TransactionRecoveryOutcome(
                    transaction_id=transaction_id,
                    action=RecoveryAction.SKIPPED_ABORTED,
                    state_before=state_before,
                    state_after=state_before,
                )

            current = self.store.read(project_id)
            if state_before is CommitJournalState.PREPARED:
                if inputs.journal.final_etag is None:
                    return self._abort_unpublished(inputs)
                publish_base_etag = (
                    inputs.journal.publish_base_etag
                    or inputs.journal.base_etag
                )
                if current.etag == publish_base_etag:
                    if inputs.journal.final_etag == publish_base_etag:
                        if (
                            inputs.latest_project is None
                            or inputs.final_project is None
                            or inputs.latest_project != inputs.final_project
                        ):
                            raise _IntegrityProblem(
                                "prepared no-change transaction lacks identical snapshots",
                            )
                        self._finalize_runtime(
                            inputs,
                            current,
                            changes=(),
                            no_change=True,
                        )
                        return TransactionRecoveryOutcome(
                            transaction_id=transaction_id,
                            action=RecoveryAction.FINALIZED_RUNTIME,
                            state_before=state_before,
                            state_after=CommitJournalState.RUNTIME_FINALIZED,
                        )
                    return self._abort_unpublished(inputs)
                self._prove_current_is_published(inputs, current)
                promoted = inputs.journal.model_copy(
                    update={
                        "state": CommitJournalState.PROJECT_REPLACED,
                        "final_etag": current.etag,
                        "updated_at": _now(),
                    },
                )
                promoted_snapshot = inputs.journal_store.compare_and_swap(
                    expected_checksum=inputs.journal_checksum,
                    value=promoted,
                )
                inputs = _replace_journal(inputs, promoted_snapshot)

            if inputs.journal.state is CommitJournalState.PROJECT_REPLACED:
                if not inputs.journal.final_etag:
                    raise _IntegrityProblem(
                        "PROJECT_REPLACED journal has no final_etag",
                    )
                if current.etag != inputs.journal.final_etag:
                    raise _IntegrityProblem(
                        "current Project ETag does not match the published transaction; "
                        "recovery will not overwrite a newer or unrelated Project",
                    )
                changes = self._prove_current_is_published(inputs, current)
                self._finalize_runtime(
                    inputs,
                    current,
                    changes=changes,
                    no_change=False,
                )
                return TransactionRecoveryOutcome(
                    transaction_id=transaction_id,
                    action=RecoveryAction.FINALIZED_RUNTIME,
                    state_before=state_before,
                    state_after=CommitJournalState.RUNTIME_FINALIZED,
                )

            if inputs.journal.state is CommitJournalState.RUNTIME_FINALIZED:
                if self._runtime_metadata_complete(inputs, current):
                    return TransactionRecoveryOutcome(
                        transaction_id=transaction_id,
                        action=RecoveryAction.ALREADY_FINALIZED,
                        state_before=state_before,
                        state_after=state_before,
                    )
                if (
                    not inputs.journal.final_etag
                    or current.etag != inputs.journal.final_etag
                ):
                    raise _IntegrityProblem(
                        "finalized Runtime metadata is incomplete and current Project "
                        "no longer matches final_etag",
                    )
                if inputs.round_record.status is TransactionStatus.NO_CHANGE:
                    self._finalize_runtime(
                        inputs,
                        current,
                        changes=(),
                        no_change=True,
                    )
                else:
                    changes = self._prove_current_is_published(inputs, current)
                    self._finalize_runtime(
                        inputs,
                        current,
                        changes=changes,
                        no_change=False,
                    )
                return TransactionRecoveryOutcome(
                    transaction_id=transaction_id,
                    action=RecoveryAction.REPAIRED_FINALIZED_RUNTIME,
                    state_before=state_before,
                    state_after=state_before,
                )

            raise _IntegrityProblem(
                f"unsupported journal state: {inputs.journal.state}",
            )
        except Exception as exc:
            return TransactionRecoveryOutcome(
                transaction_id=transaction_id,
                action=RecoveryAction.INTEGRITY_ERROR,
                state_before=state_before,
                state_after=state_before,
                detail=f"{type(exc).__name__}: {exc}",
            )

    def _load_inputs(
        self,
        project_id: str,
        runtime_root: Path,
        transaction_root: Path,
    ) -> _RecoveryInputs:
        journal_store = AtomicJsonRecordStore(
            transaction_root / "journal.json",
            ProjectCommitJournal,
        )
        journal_snapshot = journal_store.read_snapshot()
        journal = journal_snapshot.value
        if transaction_root.name != journal.transaction_id:
            raise _IntegrityProblem(
                "journal transaction_id does not match its directory",
            )
        if journal.project_id != project_id:
            raise _IntegrityProblem(
                "journal project_id does not match its Project",
            )
        if (
            journal.round_id is None
            or journal.advance_accepted_baseline is None
        ):
            raise _IntegrityProblem(
                "legacy journal lacks explicit round_id/accepted-baseline semantics",
            )

        base_value = AtomicJsonRecordStore(
            transaction_root / "base.json",
        ).read()
        candidate_value = AtomicJsonRecordStore(
            transaction_root / "candidate.json",
        ).read()
        if not isinstance(base_value, Mapping) or not isinstance(
            candidate_value,
            Mapping,
        ):
            raise _IntegrityProblem(
                "base.json and candidate.json must be JSON objects",
            )
        base_data = copy.deepcopy(dict(base_value))
        candidate_data = copy.deepcopy(dict(candidate_value))
        base_project = Project.model_validate(base_data)
        if base_project.project_id != project_id:
            raise _IntegrityProblem(
                "base Project identity does not match journal",
            )
        if project_etag(base_project) != journal.base_etag:
            raise _IntegrityProblem(
                "base.json does not match journal base_etag",
            )
        if _candidate_hash(candidate_data) != journal.candidate_etag:
            raise _IntegrityProblem(
                "candidate.json does not match journal candidate_etag",
            )

        latest_data: dict[str, Any] | None = None
        latest_project: Project | None = None
        final_data: dict[str, Any] | None = None
        final_project: Project | None = None
        latest_value = AtomicJsonRecordStore(
            transaction_root / "latest.json",
        ).read_or_none()
        final_value = AtomicJsonRecordStore(
            transaction_root / "final.json",
        ).read_or_none()
        # latest.json/final.json are written before one atomic journal update
        # records both publish ETags.  If the process dies in that narrow
        # window, PREPARED + no final_etag proves project.json was never
        # published by this transaction.  Ignore either complete dangling
        # snapshot here so recovery can safely abort instead of turning a
        # recoverable crash into a permanent integrity error.
        unpublished_partial_snapshots = (
            journal.state is CommitJournalState.PREPARED
            and journal.final_etag is None
        )
        if not unpublished_partial_snapshots and (
            (latest_value is None) != (final_value is None)
        ):
            raise _IntegrityProblem(
                "latest.json and final.json must be present together",
            )
        if (
            not unpublished_partial_snapshots
            and latest_value is not None
            and final_value is not None
        ):
            if not isinstance(latest_value, Mapping) or not isinstance(
                final_value,
                Mapping,
            ):
                raise _IntegrityProblem(
                    "latest.json and final.json must be JSON objects",
                )
            latest_data = copy.deepcopy(dict(latest_value))
            final_data = copy.deepcopy(dict(final_value))
            latest_project = Project.model_validate(latest_data)
            final_project = Project.model_validate(final_data)
            if (
                latest_project.project_id != project_id
                or final_project.project_id != project_id
            ):
                raise _IntegrityProblem(
                    "publish snapshots belong to another Project",
                )
            if journal.publish_base_etag is None:
                raise _IntegrityProblem(
                    "publish snapshots require publish_base_etag",
                )
            if project_etag(latest_project) != journal.publish_base_etag:
                raise _IntegrityProblem(
                    "latest.json does not match publish_base_etag",
                )
            if journal.final_etag is None:
                raise _IntegrityProblem("final.json requires final_etag")
            if project_etag(final_project) != journal.final_etag:
                raise _IntegrityProblem("final.json does not match final_etag")
            if final_project.generation == latest_project.generation:
                if (
                    final_data != latest_data
                    or journal.final_etag != journal.publish_base_etag
                ):
                    raise _IntegrityProblem(
                        "same-generation final snapshot must be an exact no-change result",
                    )
            elif final_project.generation != latest_project.generation + 1:
                raise _IntegrityProblem(
                    "prepared final generation must equal or follow latest generation",
                )

        requested = diff_json(base_data, candidate_data)
        protected = sorted(
            change.pointer
            for change in requested
            if is_protected_pointer(change.pointer)
        )
        if protected:
            raise _IntegrityProblem(
                f"candidate snapshot modifies protected pointers: {protected}",
            )
        if [
            change.pointer for change in requested
        ] != journal.touched_pointers:
            raise _IntegrityProblem(
                "journal touched_pointers do not match its snapshots",
            )

        aggregate_round_store = AtomicJsonRecordStore(
            runtime_root / "change-rounds" / journal.round_id / "round.json",
            ChangeRoundRecord,
        )
        transaction_round_store = AtomicJsonRecordStore(
            transaction_root / "round.json",
            ChangeRoundRecord,
        )
        transaction_round_snapshot = _read_optional_snapshot(
            transaction_round_store,
        )
        if transaction_round_snapshot is None:
            # Compatibility for journals created before transaction-scoped
            # Round facts were introduced.
            aggregate_round_snapshot = aggregate_round_store.read_snapshot()
            round_store = aggregate_round_store
            round_snapshot = aggregate_round_snapshot
        else:
            round_store = transaction_round_store
            round_snapshot = transaction_round_snapshot
        round_record = round_snapshot.value
        if (
            round_record.round_id != journal.round_id
            or round_record.project_id != project_id
        ):
            raise _IntegrityProblem(
                "ChangeRound identity does not match journal",
            )
        aggregate_round_snapshot = _read_optional_snapshot(
            aggregate_round_store,
        )
        if aggregate_round_snapshot is None:
            # The public transaction directory is renamed into place before
            # its aggregate projection is created.  This one narrow crash
            # window is unambiguous: the initial journal and transaction Round
            # are complete, Project publication has not been prepared, and
            # startup can recreate the ACTIVE projection before aborting it.
            if not (
                transaction_round_snapshot is not None
                and journal.state is CommitJournalState.PREPARED
                and journal.final_etag is None
                and round_record.status is TransactionStatus.ACTIVE
            ):
                raise _IntegrityProblem("aggregate ChangeRound is missing")
            created_aggregate = aggregate_round_store.try_create(round_record)
            aggregate_round_snapshot = (
                created_aggregate
                if created_aggregate is not None
                else aggregate_round_store.read_snapshot()
            )
        try:
            _validate_same_round(aggregate_round_snapshot.value, round_record)
        except Exception as exc:
            raise _IntegrityProblem(
                "aggregate ChangeRound provenance conflicts with transaction",
            ) from exc
        return _RecoveryInputs(
            journal=journal,
            journal_checksum=journal_snapshot.checksum,
            journal_store=journal_store,
            transaction_root=transaction_root,
            base_data=base_data,
            base_project=base_project,
            candidate_data=candidate_data,
            latest_data=latest_data,
            latest_project=latest_project,
            final_data=final_data,
            final_project=final_project,
            round_record=round_record,
            round_checksum=round_snapshot.checksum,
            round_store=round_store,
            aggregate_round_checksum=aggregate_round_snapshot.checksum,
            aggregate_round_store=aggregate_round_store,
        )

    def _abort_unpublished(
        self,
        inputs: _RecoveryInputs,
    ) -> TransactionRecoveryOutcome:
        if inputs.round_record.status not in {
            TransactionStatus.ACTIVE,
            TransactionStatus.NO_CHANGE,
            TransactionStatus.ABORTED,
        }:
            raise _IntegrityProblem(
                "unpublished transaction has an incompatible terminal ChangeRound",
            )
        if inputs.round_record.status is not TransactionStatus.ABORTED:
            aborted_round = inputs.round_record.model_copy(
                update={
                    "status": TransactionStatus.ABORTED,
                    "updated_at": _now(),
                },
            )
            inputs.round_store.compare_and_swap(
                expected_checksum=inputs.round_checksum,
                value=aborted_round,
            )
            if inputs.aggregate_round_store.path != inputs.round_store.path:
                aggregate = inputs.aggregate_round_store.read_snapshot()
                if aggregate.value.status is TransactionStatus.ACTIVE:
                    inputs.aggregate_round_store.compare_and_swap(
                        expected_checksum=aggregate.checksum,
                        value=aborted_round.model_copy(
                            update={"created_at": aggregate.value.created_at},
                        ),
                    )
        aborted = inputs.journal.model_copy(
            update={
                "state": CommitJournalState.ABORTED,
                "updated_at": _now(),
                "error": "recovery: Project was not published",
            },
        )
        inputs.journal_store.compare_and_swap(
            expected_checksum=inputs.journal_checksum,
            value=aborted,
        )
        return TransactionRecoveryOutcome(
            transaction_id=inputs.journal.transaction_id,
            action=RecoveryAction.ABORTED_UNPUBLISHED,
            state_before=CommitJournalState.PREPARED,
            state_after=CommitJournalState.ABORTED,
        )

    def _prove_current_is_published(
        self,
        inputs: _RecoveryInputs,
        current: ProjectSnapshot,
    ) -> tuple[JsonChange, ...]:
        if (
            inputs.latest_data is not None
            and inputs.latest_project is not None
            and inputs.final_data is not None
            and inputs.final_project is not None
        ):
            if current.etag != inputs.journal.final_etag:
                raise _IntegrityProblem(
                    "current Project does not match prepared final_etag",
                )
            if current.project != inputs.final_project:
                raise _IntegrityProblem(
                    "current Project differs from prepared final.json",
                )
            changes = _business_changes(inputs.latest_data, inputs.final_data)
            if not changes:
                raise _IntegrityProblem(
                    "prepared Project publication has no business changes",
                )
            return changes
        if current.generation != inputs.base_project.generation + 1:
            raise _IntegrityProblem(
                "published Project generation is not adjacent to base; "
                "pre-publish latest cannot be reconstructed safely",
            )
        candidate_changes = _business_changes(
            inputs.base_data,
            inputs.candidate_data,
        )
        current_changes = _business_changes(
            inputs.base_project.model_dump(mode="json"),
            current.project.model_dump(mode="json"),
        )
        if _change_signatures(candidate_changes) != _change_signatures(
            current_changes,
        ):
            raise _IntegrityProblem(
                "current Project is not the exact base/candidate business result",
            )
        if not current_changes:
            raise _IntegrityProblem(
                "PROJECT_REPLACED transaction has no business changes",
            )
        return current_changes

    def _runtime_metadata_complete(
        self,
        inputs: _RecoveryInputs,
        current: ProjectSnapshot,
    ) -> bool:
        if not inputs.journal.final_etag:
            raise _IntegrityProblem(
                "RUNTIME_FINALIZED journal has no final_etag",
            )
        changeset_store = self._changeset_store(inputs)
        changeset = changeset_store.read_or_none()
        state = self._state_store(inputs).read_or_none()
        if changeset is None or state is None:
            return False
        _validate_changeset_identity(changeset, inputs)
        expected_changes = (
            []
            if inputs.round_record.status is TransactionStatus.NO_CHANGE
            else [
                _runtime_change(change)
                for change in _prepared_business_changes(inputs)
            ]
        )
        if not _same_project_changes(changeset.changes, expected_changes):
            raise _IntegrityProblem(
                "ChangeSet operations conflict with transaction snapshots",
            )
        expected_round_status = _terminal_round_status(
            inputs.round_record,
            has_changes=bool(changeset.changes),
        )
        if (
            inputs.round_record.review_policy is ReviewPolicy.REQUIRE_REVIEW
            and inputs.round_record.status is TransactionStatus.COMMITTED
            and state.active_round_id != inputs.round_record.round_id
            and state.accepted_generation >= changeset.final_generation
        ):
            # A later transaction in the same Review Round may restore every
            # touched value to the accepted baseline.  The net Review then
            # disappears and the resolving transaction is directly committed.
            expected_round_status = TransactionStatus.COMMITTED
        if inputs.round_record.status is not expected_round_status:
            return False
        if state.project_id != inputs.journal.project_id:
            raise _IntegrityProblem(
                "RuntimeProjectState belongs to another Project",
            )
        if state.last_project_generation < changeset.final_generation:
            return False
        if (
            state.last_project_generation == changeset.final_generation
            and state.last_project_etag != changeset.final_etag
        ):
            raise _IntegrityProblem(
                "RuntimeProjectState final ETag conflicts with ChangeSet",
            )
        if (
            current.generation == state.last_project_generation
            and current.etag != state.last_project_etag
        ):
            raise _IntegrityProblem(
                "RuntimeProjectState conflicts with current Project",
            )
        if (
            inputs.round_record.review_policy is ReviewPolicy.REQUIRE_REVIEW
            and changeset.changes
            and inputs.round_record.status is TransactionStatus.PENDING_REVIEW
        ):
            review = self._new_review_store(inputs).read_or_none()
            if review is None:
                if (
                    state.active_round_id == inputs.round_record.round_id
                    or state.accepted_generation < changeset.final_generation
                ):
                    return False
                return True
            _validate_existing_new_review(
                review,
                inputs,
                changeset.changes,
                minimum_candidate_generation=changeset.final_generation,
            )
        return True

    def _finalize_runtime(
        self,
        inputs: _RecoveryInputs,
        current: ProjectSnapshot,
        *,
        changes: tuple[JsonChange, ...],
        no_change: bool,
    ) -> None:
        runtime_changes = [_runtime_change(change) for change in changes]
        if no_change:
            changeset = RuntimeChangeSet(
                round_id=inputs.round_record.round_id,
                project_id=inputs.journal.project_id,
                origin=inputs.round_record.origin,
                review_policy=inputs.round_record.review_policy,
                caused_by_request_id=inputs.round_record.caused_by_request_id,
                caused_by_message_seq=inputs.round_record.caused_by_message_seq,
                base_generation=current.generation,
                final_generation=current.generation,
                base_etag=current.etag,
                final_etag=current.etag,
                changes=[],
            )
        else:
            publish_base_project = inputs.latest_project or inputs.base_project
            publish_base_etag = (
                inputs.journal.publish_base_etag or inputs.journal.base_etag
            )
            changeset = RuntimeChangeSet(
                round_id=inputs.round_record.round_id,
                project_id=inputs.journal.project_id,
                origin=inputs.round_record.origin,
                review_policy=inputs.round_record.review_policy,
                caused_by_request_id=inputs.round_record.caused_by_request_id,
                caused_by_message_seq=inputs.round_record.caused_by_message_seq,
                base_generation=publish_base_project.generation,
                final_generation=current.generation,
                base_etag=publish_base_etag,
                final_etag=current.etag,
                changes=runtime_changes,
            )

        changeset_store = self._changeset_store(inputs)
        existing_changeset = _read_optional_snapshot(changeset_store)
        if existing_changeset is not None:
            if not _same_changeset(existing_changeset.value, changeset):
                raise _IntegrityProblem(
                    "existing ChangeSet conflicts with recovery result",
                )

        state_store = self._state_store(inputs)
        existing_state = _read_optional_snapshot(state_store)
        new_review_plan: _NewReviewPlan | None = None
        existing_review_update: _ExistingReviewUpdate | None = None
        active_round_id: str | None = None
        accepted = False

        if (
            inputs.round_record.review_policy is ReviewPolicy.REQUIRE_REVIEW
            and not no_change
        ):
            if (
                existing_state is not None
                and existing_state.value.active_round_id is not None
                and existing_state.value.active_round_id
                != inputs.round_record.round_id
            ):
                active_review = AtomicJsonRecordStore(
                    self.store.project_root(inputs.journal.project_id)
                    / "runtime"
                    / "reviews"
                    / f"review-{existing_state.value.active_round_id}"
                    / "review.json",
                    ReviewRecord,
                ).read_or_none()
                if (
                    active_review is not None
                    and active_review.status is ReviewStatus.PENDING
                ):
                    raise _IntegrityProblem(
                        "another Review is still pending for this Project",
                    )
            new_review_plan = self._prepare_new_review(
                inputs,
                current,
                runtime_changes,
            )
            if new_review_plan.value.status is ReviewStatus.PENDING:
                active_round_id = inputs.round_record.round_id
            else:
                accepted = True
        else:
            existing_review_update = self._prepare_existing_review_update(
                inputs,
                current,
                runtime_changes,
                existing_state.value if existing_state is not None else None,
            )
            if existing_review_update is not None:
                if existing_review_update.pending:
                    active_round_id = existing_review_update.value.round_id
                else:
                    accepted = True
            elif inputs.journal.advance_accepted_baseline:
                accepted = True
            elif existing_state is None:
                raise _IntegrityProblem(
                    "cannot preserve accepted baseline without RuntimeProjectState",
                )
            else:
                active_round_id = existing_state.value.active_round_id

        state = _build_runtime_state(
            inputs=inputs,
            current=current,
            existing=existing_state.value
            if existing_state is not None
            else None,
            accepted=accepted,
            active_round_id=active_round_id,
        )
        terminal_status = (
            TransactionStatus.NO_CHANGE
            if no_change
            else (
                TransactionStatus.PENDING_REVIEW
                if new_review_plan is not None
                and new_review_plan.value.status is ReviewStatus.PENDING
                else TransactionStatus.COMMITTED
            )
        )
        if inputs.round_record.status not in {
            TransactionStatus.ACTIVE,
            terminal_status,
        }:
            raise _IntegrityProblem(
                f"ChangeRound status cannot be recovered: {inputs.round_record.status}",
            )

        # All existing records are read and checked before the first write.
        if existing_changeset is None:
            created = changeset_store.try_create(changeset)
            if created is None:
                concurrent = changeset_store.read()
                if not _same_changeset(concurrent, changeset):
                    raise _IntegrityProblem(
                        "concurrent ChangeSet conflicts with recovery",
                    )
        aggregate_changeset_store = self._aggregate_changeset_store(inputs)
        if aggregate_changeset_store.path != changeset_store.path:
            aggregate_changeset = aggregate_changeset_store.read_or_none()
            if aggregate_changeset is None:
                aggregate_changeset_store.create(changeset)
            elif (
                not no_change
                and aggregate_changeset.final_generation
                < changeset.final_generation
            ):
                aggregate_changeset_store.write(changeset)
        if new_review_plan is not None and new_review_plan.existing is None:
            created = new_review_plan.store.try_create(new_review_plan.value)
            if created is None:
                concurrent = new_review_plan.store.read()
                _validate_existing_new_review(
                    concurrent,
                    inputs,
                    runtime_changes,
                    expected_candidate_etag=current.etag,
                    minimum_candidate_generation=current.generation,
                )
        if existing_review_update is not None:
            existing_review_update.store.compare_and_swap(
                expected_checksum=existing_review_update.checksum,
                value=existing_review_update.value,
            )
        if inputs.round_record.status is not terminal_status:
            inputs.round_store.compare_and_swap(
                expected_checksum=inputs.round_checksum,
                value=inputs.round_record.model_copy(
                    update={"status": terminal_status, "updated_at": _now()},
                ),
            )
        if inputs.aggregate_round_store.path != inputs.round_store.path:
            aggregate_round = inputs.aggregate_round_store.read_snapshot()
            should_update_aggregate = (
                not no_change
                or aggregate_round.value.status
                in {TransactionStatus.ACTIVE, TransactionStatus.ABORTED}
            )
            if should_update_aggregate:
                inputs.aggregate_round_store.compare_and_swap(
                    expected_checksum=aggregate_round.checksum,
                    value=inputs.round_record.model_copy(
                        update={
                            "status": terminal_status,
                            "created_at": aggregate_round.value.created_at,
                            "updated_at": _now(),
                        },
                    ),
                )
        _update_manual_edit_buffer(self.store, changeset)
        if existing_state is None:
            created = state_store.try_create(state)
            if created is None:
                raise _IntegrityProblem(
                    "RuntimeProjectState appeared during recovery",
                )
        else:
            state_store.compare_and_swap(
                expected_checksum=existing_state.checksum,
                value=state,
            )

        if inputs.journal.state in {
            CommitJournalState.PREPARED,
            CommitJournalState.PROJECT_REPLACED,
        }:
            inputs.journal_store.compare_and_swap(
                expected_checksum=inputs.journal_checksum,
                value=inputs.journal.model_copy(
                    update={
                        "state": CommitJournalState.RUNTIME_FINALIZED,
                        "updated_at": _now(),
                    },
                ),
            )

    def _prepare_new_review(
        self,
        inputs: _RecoveryInputs,
        current: ProjectSnapshot,
        changes: list[ProjectChange],
    ) -> _NewReviewPlan:
        boundary = inputs.round_record.review_boundary
        if boundary is None or not changes:
            raise _IntegrityProblem(
                "review-required recovery lacks boundary or changes",
            )
        store = self._new_review_store(inputs)
        existing = _read_optional_snapshot(store)
        if existing is not None:
            _validate_existing_new_review(
                existing.value,
                inputs,
                changes,
                expected_candidate_etag=current.etag,
                minimum_candidate_generation=current.generation,
            )
            return _NewReviewPlan(
                store=store,
                existing=existing,
                value=existing.value,
            )
        operations = [
            ReviewOperation(
                **change.model_dump(mode="python"),
                operation_id=_review_operation_id(
                    inputs.round_record.round_id,
                    change,
                ),
            )
            for change in changes
        ]
        review = ReviewRecord(
            review_id=f"review-{inputs.round_record.round_id}",
            round_id=inputs.round_record.round_id,
            request_id=boundary.request_id,
            request_message_seq=boundary.request_message_seq,
            interrupted_run_id=boundary.interrupted_run_id,
            baseline_generation=boundary.accepted_generation,
            baseline_etag=boundary.accepted_etag,
            candidate_generation=current.generation,
            candidate_etag=current.etag,
            decision_token=secrets.token_urlsafe(24),
            operations=operations,
        )
        return _NewReviewPlan(store=store, existing=None, value=review)

    def _prepare_existing_review_update(
        self,
        inputs: _RecoveryInputs,
        current: ProjectSnapshot,
        changes: list[ProjectChange],
        state: RuntimeProjectState | None,
    ) -> _ExistingReviewUpdate | None:
        if state is None or not state.active_round_id:
            return None
        store = AtomicJsonRecordStore(
            self.store.project_root(inputs.journal.project_id)
            / "runtime"
            / "reviews"
            / f"review-{state.active_round_id}"
            / "review.json",
            ReviewRecord,
        )
        snapshot = _read_optional_snapshot(store)
        if snapshot is None:
            raise _IntegrityProblem("active Runtime review is missing")
        review = snapshot.value
        if review.status in {ReviewStatus.RESOLVED, ReviewStatus.SUPERSEDED}:
            if any(
                operation.decision is ReviewOperationDecision.PENDING
                for operation in review.operations
            ):
                raise _IntegrityProblem(
                    "resolved active Runtime review still has pending operations",
                )
            if (
                review.candidate_generation != current.generation
                or review.candidate_etag != current.etag
            ):
                raise _IntegrityProblem(
                    "resolved active Runtime review does not match current Project",
                )
            # Crash window: Review reconciliation was durable but state.json
            # still points at it. Treat the durable resolved Review as proof
            # and let the caller clear active_round_id/advance the baseline.
            return _ExistingReviewUpdate(
                store=store,
                checksum=snapshot.checksum,
                value=review,
                pending=False,
            )
        if review.status is not ReviewStatus.PENDING:
            raise _IntegrityProblem(
                "active Runtime review has an invalid status",
            )
        touched = [
            change.json_pointer for change in changes if change.json_pointer
        ]
        operations: list[ReviewOperation] = []
        for operation in review.operations:
            if (
                inputs.round_record.origin is ChangeOrigin.FRONTEND_EDIT
                and operation.decision is ReviewOperationDecision.PENDING
                and operation.json_pointer is not None
                and any(
                    pointers_overlap(operation.json_pointer, pointer)
                    for pointer in touched
                )
            ):
                operation = operation.model_copy(
                    update={
                        "decision": ReviewOperationDecision.SUPERSEDED_BY_USER_EDIT,
                    },
                )
            operations.append(operation)
        pending = any(
            operation.decision is ReviewOperationDecision.PENDING
            for operation in operations
        )
        updated = ReviewRecord.model_validate(
            review.model_copy(
                update={
                    "candidate_generation": current.generation,
                    "candidate_etag": current.etag,
                    "decision_token": secrets.token_urlsafe(24),
                    "status": ReviewStatus.PENDING
                    if pending
                    else ReviewStatus.RESOLVED,
                    "operations": operations,
                    "updated_at": _now(),
                },
            ).model_dump(mode="python"),
        )
        return _ExistingReviewUpdate(
            store=store,
            checksum=snapshot.checksum,
            value=updated,
            pending=pending,
        )

    def _changeset_store(
        self,
        inputs: _RecoveryInputs,
    ) -> AtomicJsonRecordStore[RuntimeChangeSet]:
        transaction_store = AtomicJsonRecordStore(
            inputs.transaction_root / "changeset.json",
            RuntimeChangeSet,
        )
        if transaction_store.path.exists():
            return transaction_store
        # Legacy fallback.  New recovery always creates transaction-scoped
        # evidence before touching the mutable Round-level projection.
        if not (inputs.transaction_root / "round.json").exists():
            return AtomicJsonRecordStore(
                self.store.project_root(inputs.journal.project_id)
                / "runtime"
                / "change-rounds"
                / inputs.round_record.round_id
                / "changeset.json",
                RuntimeChangeSet,
            )
        return transaction_store

    def _aggregate_changeset_store(
        self,
        inputs: _RecoveryInputs,
    ) -> AtomicJsonRecordStore[RuntimeChangeSet]:
        return AtomicJsonRecordStore(
            self.store.project_root(inputs.journal.project_id)
            / "runtime"
            / "change-rounds"
            / inputs.round_record.round_id
            / "changeset.json",
            RuntimeChangeSet,
        )

    def _state_store(
        self,
        inputs: _RecoveryInputs,
    ) -> AtomicJsonRecordStore[RuntimeProjectState]:
        return AtomicJsonRecordStore(
            self.store.project_root(inputs.journal.project_id)
            / "runtime"
            / "state.json",
            RuntimeProjectState,
        )

    def _new_review_store(
        self,
        inputs: _RecoveryInputs,
    ) -> AtomicJsonRecordStore[ReviewRecord]:
        return AtomicJsonRecordStore(
            self.store.project_root(inputs.journal.project_id)
            / "runtime"
            / "reviews"
            / f"review-{inputs.round_record.round_id}"
            / "review.json",
            ReviewRecord,
        )


def _replace_journal(
    inputs: _RecoveryInputs,
    snapshot: RecordSnapshot[ProjectCommitJournal],
) -> _RecoveryInputs:
    return _RecoveryInputs(
        journal=snapshot.value,
        journal_checksum=snapshot.checksum,
        journal_store=inputs.journal_store,
        transaction_root=inputs.transaction_root,
        base_data=inputs.base_data,
        base_project=inputs.base_project,
        candidate_data=inputs.candidate_data,
        latest_data=inputs.latest_data,
        latest_project=inputs.latest_project,
        final_data=inputs.final_data,
        final_project=inputs.final_project,
        round_record=inputs.round_record,
        round_checksum=inputs.round_checksum,
        round_store=inputs.round_store,
        aggregate_round_checksum=inputs.aggregate_round_checksum,
        aggregate_round_store=inputs.aggregate_round_store,
    )


def _business_changes(before: Any, after: Any) -> tuple[JsonChange, ...]:
    return tuple(
        change
        for change in diff_json(before, after)
        if not is_protected_pointer(change.pointer)
    )


def _prepared_business_changes(
    inputs: _RecoveryInputs,
) -> tuple[JsonChange, ...]:
    if inputs.latest_data is not None and inputs.final_data is not None:
        return _business_changes(inputs.latest_data, inputs.final_data)
    return _business_changes(inputs.base_data, inputs.candidate_data)


def _change_signatures(
    changes: tuple[JsonChange, ...],
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (change.kind, change.pointer, change.before_hash, change.after_hash)
        for change in changes
    )


def _same_changeset(left: RuntimeChangeSet, right: RuntimeChangeSet) -> bool:
    left_data = left.model_dump(mode="json", exclude={"created_at"})
    right_data = right.model_dump(mode="json", exclude={"created_at"})
    return left_data == right_data


def _validate_changeset_identity(
    changeset: RuntimeChangeSet,
    inputs: _RecoveryInputs,
) -> None:
    if (
        changeset.round_id != inputs.round_record.round_id
        or changeset.project_id != inputs.journal.project_id
        or changeset.origin is not inputs.round_record.origin
        or changeset.review_policy is not inputs.round_record.review_policy
        or changeset.caused_by_request_id
        != inputs.round_record.caused_by_request_id
        or changeset.caused_by_message_seq
        != inputs.round_record.caused_by_message_seq
        or changeset.final_etag != inputs.journal.final_etag
    ):
        raise _IntegrityProblem(
            "ChangeSet identity/provenance conflicts with journal",
        )
    if changeset.changes:
        # A stale but field-disjoint candidate may have been merged onto a
        # newer pre-publish Project.  The journal's base_etag is the caller's
        # base, while ChangeSet.base_etag correctly records that newer latest.
        if changeset.base_generation < inputs.base_project.generation:
            raise _IntegrityProblem(
                "ChangeSet base generation precedes journal base",
            )
        if (
            inputs.journal.publish_base_etag is not None
            and changeset.base_etag != inputs.journal.publish_base_etag
        ):
            raise _IntegrityProblem(
                "ChangeSet base ETag conflicts with prepared publication",
            )
    elif changeset.base_etag != changeset.final_etag:
        raise _IntegrityProblem("no-change ChangeSet must use one ETag")


def _same_project_changes(
    left: list[ProjectChange],
    right: list[ProjectChange],
) -> bool:
    return [item.model_dump(mode="json") for item in left] == [
        item.model_dump(mode="json") for item in right
    ]


def _terminal_round_status(
    round_record: ChangeRoundRecord,
    *,
    has_changes: bool,
) -> TransactionStatus:
    if not has_changes:
        return TransactionStatus.NO_CHANGE
    if round_record.review_policy is ReviewPolicy.REQUIRE_REVIEW:
        return TransactionStatus.PENDING_REVIEW
    return TransactionStatus.COMMITTED


def _validate_existing_new_review(
    review: ReviewRecord,
    inputs: _RecoveryInputs,
    changes: list[ProjectChange],
    *,
    expected_candidate_etag: str | None = None,
    minimum_candidate_generation: int | None = None,
) -> None:
    boundary = inputs.round_record.review_boundary
    if boundary is None:
        raise _IntegrityProblem("review-required round has no ReviewBoundary")
    if (
        review.review_id != f"review-{inputs.round_record.round_id}"
        or review.round_id != inputs.round_record.round_id
        or review.request_id != boundary.request_id
        or review.request_message_seq != boundary.request_message_seq
        or review.interrupted_run_id != boundary.interrupted_run_id
        or review.baseline_generation != boundary.accepted_generation
        or review.baseline_etag != boundary.accepted_etag
    ):
        raise _IntegrityProblem(
            "Review identity/baseline conflicts with journal",
        )
    if (
        expected_candidate_etag is not None
        and review.candidate_etag != expected_candidate_etag
    ):
        raise _IntegrityProblem(
            "Review candidate ETag conflicts with recovered Project",
        )
    if minimum_candidate_generation is not None:
        if review.candidate_generation < minimum_candidate_generation:
            raise _IntegrityProblem(
                "Review candidate generation precedes its ChangeSet",
            )
        if (
            review.candidate_generation == minimum_candidate_generation
            and review.candidate_etag != inputs.journal.final_etag
        ):
            raise _IntegrityProblem(
                "Review candidate ETag conflicts at final generation",
            )
    # One logical Review Round may contain several immutable transactions.
    # The Review is their net projection, so it may legitimately contain
    # operations from earlier transactions and preserve an earlier before hash.
    # At the exact transaction generation, however, every touched locator must
    # be represented with that transaction's resulting after hash.
    if (
        minimum_candidate_generation is not None
        and review.candidate_generation == minimum_candidate_generation
    ):
        actual_by_locator = {
            (
                operation.json_pointer,
                operation.file_id,
                operation.target_ref,
            ): operation
            for operation in review.operations
        }
        if len(actual_by_locator) != len(review.operations):
            raise _IntegrityProblem(
                "Review contains duplicate operation locators",
            )
        for change in changes:
            locator = (change.json_pointer, change.file_id, change.target_ref)
            operation = actual_by_locator.get(locator)
            if operation is None or operation.after_hash != change.after_hash:
                raise _IntegrityProblem(
                    "Review operations conflict with recovered ChangeSet",
                )


def _build_runtime_state(
    *,
    inputs: _RecoveryInputs,
    current: ProjectSnapshot,
    existing: RuntimeProjectState | None,
    accepted: bool,
    active_round_id: str | None,
) -> RuntimeProjectState:
    if (
        existing is not None
        and existing.last_project_generation > current.generation
    ):
        raise _IntegrityProblem(
            "RuntimeProjectState is ahead of current Project",
        )
    boundary = inputs.round_record.review_boundary
    if accepted:
        accepted_generation = current.generation
        accepted_etag = current.etag
    elif boundary is not None:
        accepted_generation = boundary.accepted_generation
        accepted_etag = boundary.accepted_etag
    elif existing is not None:
        accepted_generation = existing.accepted_generation
        accepted_etag = existing.accepted_etag
    else:
        raise _IntegrityProblem(
            "accepted Project baseline cannot be reconstructed",
        )
    return RuntimeProjectState(
        project_id=inputs.journal.project_id,
        active_session_id=existing.active_session_id if existing else None,
        active_goal_id=existing.active_goal_id if existing else None,
        active_round_id=active_round_id,
        last_project_generation=current.generation,
        last_project_etag=current.etag,
        accepted_generation=accepted_generation,
        accepted_etag=accepted_etag,
        sync_status=SyncStatus.HEALTHY,
    )


def _read_optional_snapshot(
    store: AtomicJsonRecordStore[T],
) -> RecordSnapshot[T] | None:
    try:
        return store.read_snapshot()
    except RecordNotFoundError:
        return None


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "CreatorRecoveryReport",
    "ProjectCommitRecoveryCoordinator",
    "ProjectRecoveryIntegrityError",
    "ProjectRecoveryReport",
    "RecoveryAction",
    "TransactionRecoveryOutcome",
]

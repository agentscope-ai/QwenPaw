# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches
"""Filesystem Runtime Review decisions over real Project JSON values."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
import secrets
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.jsonl_store import DurableJsonlStore
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.models import (
    ReviewOperationDecision,
    ReviewRecord,
    ReviewStatus,
    RuntimeProjectState,
)
from services.runtime_files.errors import RuntimeFileValidationError
from services.runtime_files.path_safety import (
    hashed_runtime_segment,
    require_safe_runtime_segment,
)

from .commit import (
    CommitJournalState,
    ProjectCommitBoundary,
    ProjectCommitJournal,
)
from .json_pointer import (
    MISSING,
    JsonChange,
    apply_changes,
    hash_json_value,
    value_at,
)
from .store import ProjectSnapshot, ProjectStore
from .models import Project
from .serialization import project_etag


ReviewDecisionValue = Literal["ACCEPT", "REJECT"]


class ReviewDecisionError(RuntimeError):
    pass


class ReviewNotFound(ReviewDecisionError):
    pass


class ReviewDecisionConflict(ReviewDecisionError):
    pass


class ReviewDecisionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=1)
    decision: ReviewDecisionValue


class ReviewDecisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    review_id: str
    decision_token: str
    decisions: list[ReviewDecisionItem]
    resulting_generation: int
    resulting_etag: str
    created_at: datetime


class ReviewDecisionJournalState(StrEnum):
    """Durable phases of one idempotent Review decision."""

    PREPARED = "PREPARED"
    PROJECT_APPLIED = "PROJECT_APPLIED"
    FINALIZED = "FINALIZED"


class ReviewDecisionRecoveryAction(StrEnum):
    """Outcome of startup reconciliation for one decision journal."""

    FINALIZED = "finalized"
    ALREADY_FINALIZED = "already_finalized"
    INTEGRITY_ERROR = "integrity_error"


@dataclass(frozen=True, slots=True)
class ReviewDecisionRecoveryOutcome:
    project_id: str
    review_id: str
    decision_id: str
    action: ReviewDecisionRecoveryAction
    state_before: ReviewDecisionJournalState | None
    state_after: ReviewDecisionJournalState | None
    detail: str | None = None

    @property
    def integrity_error(self) -> bool:
        return self.action is ReviewDecisionRecoveryAction.INTEGRITY_ERROR


@dataclass(frozen=True, slots=True)
class ProjectReviewRecoveryReport:
    project_id: str
    outcomes: tuple[ReviewDecisionRecoveryOutcome, ...]

    @property
    def integrity_errors(self) -> tuple[ReviewDecisionRecoveryOutcome, ...]:
        return tuple(item for item in self.outcomes if item.integrity_error)

    @property
    def ok(self) -> bool:
        return not self.integrity_errors


@dataclass(frozen=True, slots=True)
class CreatorReviewRecoveryReport:
    projects: tuple[ProjectReviewRecoveryReport, ...]

    @property
    def integrity_errors(self) -> tuple[ReviewDecisionRecoveryOutcome, ...]:
        return tuple(
            outcome
            for project in self.projects
            for outcome in project.integrity_errors
        )

    @property
    def ok(self) -> bool:
        return not self.integrity_errors


class ReviewDecisionJournal(BaseModel):
    """Write-ahead record for a Review decision.

    The opaque ``decision_id`` is data only.  Its directory is always a
    length-prefixed hash, so a client-controlled identifier can never become a
    filesystem path segment.
    """

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1, max_length=192)
    project_id: str = Field(min_length=1)
    review_id: str = Field(min_length=1)
    decision_token: str = Field(min_length=1)
    decisions: list[ReviewDecisionItem] = Field(min_length=1)
    state: ReviewDecisionJournalState
    review_before: ReviewRecord
    project_before_generation: int = Field(ge=0)
    project_before_etag: str = Field(min_length=1)
    compensation_required: bool
    compensation_transaction_id: str | None = None
    compensation_round_id: str | None = None
    resulting_generation: int | None = Field(default=None, ge=0)
    resulting_etag: str | None = None
    final_review: ReviewRecord | None = None
    event: ReviewDecisionEvent | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_phase(self) -> ReviewDecisionJournal:
        if self.compensation_required and (
            self.compensation_transaction_id is None
            or self.compensation_round_id is None
        ):
            raise ValueError(
                "a compensating decision needs stable Runtime IDs",
            )
        if not self.compensation_required and (
            self.compensation_transaction_id is not None
            or self.compensation_round_id is not None
        ):
            raise ValueError(
                "an accept-only decision cannot have compensation IDs",
            )
        if self.state is not ReviewDecisionJournalState.PREPARED and (
            self.resulting_generation is None
            or self.resulting_etag is None
            or self.final_review is None
            or self.event is None
        ):
            raise ValueError(
                "an applied Review decision needs its durable result",
            )
        return self


class ProjectReviewService:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self.commits = ProjectCommitBoundary(store)

    def active(self, project_id: str) -> ReviewRecord | None:
        all_pending = self.all_pending(project_id)
        return all_pending[0] if all_pending else None

    def all_pending(self, project_id: str) -> list[ReviewRecord]:
        runtime_root = self.store.project_root(project_id) / "runtime"
        reviews_root = runtime_root / "reviews"
        if not reviews_root.is_dir():
            return []
        candidates: list[ReviewRecord] = []
        for child in reviews_root.iterdir():
            if child.is_symlink() or not child.is_dir():
                continue
            review = AtomicJsonRecordStore(
                child / "review.json",
                ReviewRecord,
            ).read_or_none()
            if review is not None and review.status is ReviewStatus.PENDING:
                candidates.append(review)
        return sorted(candidates, key=lambda item: item.created_at)

    def get(self, project_id: str, review_id: str) -> ReviewRecord:
        review = self._review_store(project_id, review_id).read_or_none()
        if review is None:
            raise ReviewNotFound(f"Review not found: {review_id}")
        return review

    def recover_project(
        self,
        project_id: str,
        *,
        _lifecycle_lock_held: bool = False,
    ) -> ProjectReviewRecoveryReport:
        """Resume every durable Review decision for one Project.

        Project commit recovery must run before this method.  A decision may
        point at a compensating Project transaction, and that transaction must
        have reached a provable terminal Runtime state before the Review fact
        can be finalized.
        """

        lifecycle_lock = (
            nullcontext()
            if _lifecycle_lock_held
            else self.store.lifecycle_lock(project_id)
        )
        with lifecycle_lock:
            self.store.read(project_id)
            journals, outcomes = self._discover_decision_journals(project_id)
            for journal_store, journal in sorted(
                journals,
                key=lambda item: (
                    item[1].created_at,
                    item[1].review_id,
                    item[1].decision_id,
                ),
            ):
                state_before = journal.state
                if state_before is ReviewDecisionJournalState.FINALIZED:
                    outcomes.append(
                        ReviewDecisionRecoveryOutcome(
                            project_id=project_id,
                            review_id=journal.review_id,
                            decision_id=journal.decision_id,
                            action=ReviewDecisionRecoveryAction.ALREADY_FINALIZED,
                            state_before=state_before,
                            state_after=state_before,
                        ),
                    )
                    continue
                try:
                    self.decide(
                        project_id=project_id,
                        review_id=journal.review_id,
                        decision_token=journal.decision_token,
                        decisions=journal.decisions,
                        decision_id=journal.decision_id,
                        _lifecycle_lock_held=True,
                    )
                    recovered = journal_store.read()
                    if (
                        recovered.state
                        is not ReviewDecisionJournalState.FINALIZED
                    ):
                        raise ReviewDecisionConflict(
                            "Review decision recovery did not reach FINALIZED",
                        )
                    outcomes.append(
                        ReviewDecisionRecoveryOutcome(
                            project_id=project_id,
                            review_id=journal.review_id,
                            decision_id=journal.decision_id,
                            action=ReviewDecisionRecoveryAction.FINALIZED,
                            state_before=state_before,
                            state_after=recovered.state,
                        ),
                    )
                except Exception as exc:
                    current = journal_store.read_or_none()
                    outcomes.append(
                        ReviewDecisionRecoveryOutcome(
                            project_id=project_id,
                            review_id=journal.review_id,
                            decision_id=journal.decision_id,
                            action=ReviewDecisionRecoveryAction.INTEGRITY_ERROR,
                            state_before=state_before,
                            state_after=current.state
                            if current is not None
                            else None,
                            detail=f"{type(exc).__name__}: {exc}",
                        ),
                    )
        return ProjectReviewRecoveryReport(
            project_id=project_id,
            outcomes=tuple(outcomes),
        )

    def recover_all(self) -> CreatorReviewRecoveryReport:
        """Recover all discoverable Projects without one failure halting boot."""

        reports: list[ProjectReviewRecoveryReport] = []
        for project_id in self.store.discover_project_ids():
            try:
                reports.append(self.recover_project(project_id))
            except Exception as exc:
                reports.append(
                    ProjectReviewRecoveryReport(
                        project_id=project_id,
                        outcomes=(
                            ReviewDecisionRecoveryOutcome(
                                project_id=project_id,
                                review_id="<project>",
                                decision_id="<project>",
                                action=ReviewDecisionRecoveryAction.INTEGRITY_ERROR,
                                state_before=None,
                                state_after=None,
                                detail=f"{type(exc).__name__}: {exc}",
                            ),
                        ),
                    ),
                )
        return CreatorReviewRecoveryReport(projects=tuple(reports))

    def _discover_decision_journals(
        self,
        project_id: str,
    ) -> tuple[
        list[
            tuple[
                AtomicJsonRecordStore[ReviewDecisionJournal],
                ReviewDecisionJournal,
            ]
        ],
        list[ReviewDecisionRecoveryOutcome],
    ]:
        runtime_root = self.store.project_root(project_id) / "runtime"
        reviews_root = runtime_root / "reviews"
        journals: list[
            tuple[
                AtomicJsonRecordStore[ReviewDecisionJournal],
                ReviewDecisionJournal,
            ]
        ] = []
        outcomes: list[ReviewDecisionRecoveryOutcome] = []
        if not reviews_root.exists() and not reviews_root.is_symlink():
            return journals, outcomes
        if reviews_root.is_symlink() or not reviews_root.is_dir():
            outcomes.append(
                self._review_recovery_integrity_error(
                    project_id=project_id,
                    review_id="<reviews-root>",
                    decision_id="<reviews-root>",
                    detail="runtime/reviews must be a real directory",
                ),
            )
            return journals, outcomes

        for review_root in sorted(
            reviews_root.iterdir(),
            key=lambda item: item.name,
        ):
            if review_root.name.startswith("."):
                continue
            if review_root.is_symlink() or not review_root.is_dir():
                outcomes.append(
                    self._review_recovery_integrity_error(
                        project_id=project_id,
                        review_id=review_root.name,
                        decision_id="<review-root>",
                        detail="Review Runtime entry must be a real directory",
                    ),
                )
                continue
            transactions_root = review_root / "decision-transactions"
            if (
                not transactions_root.exists()
                and not transactions_root.is_symlink()
            ):
                continue
            if (
                transactions_root.is_symlink()
                or not transactions_root.is_dir()
            ):
                outcomes.append(
                    self._review_recovery_integrity_error(
                        project_id=project_id,
                        review_id=review_root.name,
                        decision_id="<decision-transactions>",
                        detail="decision-transactions must be a real directory",
                    ),
                )
                continue
            for decision_root in sorted(
                transactions_root.iterdir(),
                key=lambda item: item.name,
            ):
                if decision_root.name.startswith("."):
                    continue
                if decision_root.is_symlink() or not decision_root.is_dir():
                    outcomes.append(
                        self._review_recovery_integrity_error(
                            project_id=project_id,
                            review_id=review_root.name,
                            decision_id=decision_root.name,
                            detail="decision transaction must be a real directory",
                        ),
                    )
                    continue
                journal_store = AtomicJsonRecordStore(
                    decision_root / "journal.json",
                    ReviewDecisionJournal,
                )
                try:
                    journal = journal_store.read()
                    if journal.project_id != project_id:
                        raise ReviewDecisionConflict(
                            "decision journal Project identity is inconsistent",
                        )
                    if journal.review_id != review_root.name:
                        raise ReviewDecisionConflict(
                            "decision journal Review identity is inconsistent",
                        )
                    expected_key = hashed_runtime_segment(
                        "decision",
                        journal.decision_id,
                    )
                    if decision_root.name != expected_key:
                        raise ReviewDecisionConflict(
                            "decision journal path does not match its identity",
                        )
                    journals.append((journal_store, journal))
                except Exception as exc:
                    outcomes.append(
                        self._review_recovery_integrity_error(
                            project_id=project_id,
                            review_id=review_root.name,
                            decision_id=decision_root.name,
                            detail=f"{type(exc).__name__}: {exc}",
                        ),
                    )
        return journals, outcomes

    @staticmethod
    def _review_recovery_integrity_error(
        *,
        project_id: str,
        review_id: str,
        decision_id: str,
        detail: str,
    ) -> ReviewDecisionRecoveryOutcome:
        return ReviewDecisionRecoveryOutcome(
            project_id=project_id,
            review_id=review_id,
            decision_id=decision_id,
            action=ReviewDecisionRecoveryAction.INTEGRITY_ERROR,
            state_before=None,
            state_after=None,
            detail=detail,
        )

    def decide(
        self,
        *,
        project_id: str,
        review_id: str,
        decision_token: str,
        decisions: list[ReviewDecisionItem],
        decision_id: str | None = None,
        _lifecycle_lock_held: bool = False,
    ) -> ReviewRecord:
        # Establish the Project authority before deriving any Runtime path.  A
        # missing Project must not be materialized accidentally by lock/store
        # helpers creating parent directories.
        self.store.read(project_id)
        if not decisions:
            raise ReviewDecisionError(
                "at least one Review decision is required",
            )
        if len({item.operation_id for item in decisions}) != len(decisions):
            raise ReviewDecisionError(
                "an operation can be decided only once per request",
            )
        canonical_decisions = sorted(
            (ReviewDecisionItem.model_validate(item) for item in decisions),
            key=lambda item: item.operation_id,
        )
        try:
            review_id = require_safe_runtime_segment(
                review_id,
                label="Review id",
            )
        except RuntimeFileValidationError as exc:
            raise ReviewDecisionError(str(exc)) from exc
        runtime_root = self.store.project_root(project_id) / "runtime"
        decision_id = decision_id or f"review-decision-{uuid4().hex}"
        if (
            not isinstance(decision_id, str)
            or not decision_id
            or decision_id != decision_id.strip()
            or len(decision_id) > 192
        ):
            raise ReviewDecisionError(
                "decision id must contain 1 to 192 characters",
            )
        order_lock = CrossProcessFileLock(
            runtime_root / "locks" / "project-commit-order.lock",
            timeout_seconds=10.0,
        )
        decision_lock = CrossProcessFileLock(
            runtime_root / "locks" / f"{review_id}.decision.lock",
            timeout_seconds=10.0,
        )
        # Review decisions and ordinary Project commits both mutate the active
        # Review/accepted baseline.  Serializing them by the same generation
        # order lock prevents an accept-only decision from racing a frontend
        # commit and overwriting its superseded-operation result.
        lifecycle_lock = (
            nullcontext()
            if _lifecycle_lock_held
            else self.store.lifecycle_lock(project_id)
        )
        with lifecycle_lock:
            # The initial authority check can race delete.  Revalidate after
            # lifecycle admission and before any Project-local lock path is
            # opened/created.
            self.store.read(project_id)
            with order_lock, decision_lock:
                return self._decide_locked(
                    project_id=project_id,
                    review_id=review_id,
                    decision_token=decision_token,
                    decisions=canonical_decisions,
                    decision_id=decision_id,
                    runtime_root=runtime_root,
                )

    def _decide_locked(
        self,
        *,
        project_id: str,
        review_id: str,
        decision_token: str,
        decisions: list[ReviewDecisionItem],
        decision_id: str,
        runtime_root: Path,
    ) -> ReviewRecord:
        store = self._review_store(project_id, review_id)
        journal_store = self._decision_journal_store(
            runtime_root=runtime_root,
            review_id=review_id,
            decision_id=decision_id,
        )
        journal = journal_store.read_or_none()
        if journal is not None:
            self._validate_idempotent_request(
                journal=journal,
                project_id=project_id,
                review_id=review_id,
                decision_token=decision_token,
                decisions=decisions,
            )
            if journal.state is ReviewDecisionJournalState.FINALIZED:
                if (
                    journal.final_review is None
                ):  # pragma: no cover - model invariant
                    raise ReviewDecisionConflict(
                        "finalized decision has no Review result",
                    )
                return journal.final_review
            self._assert_no_other_active_decision(
                project_id=project_id,
                runtime_root=runtime_root,
                review_id=review_id,
                decision_id=decision_id,
            )
        else:
            # The Review-level decision lock covers this scan and the journal
            # create below.  Two concurrent callers therefore cannot both
            # observe an empty active set and publish different PREPARED
            # journals for the same Review/token.
            self._assert_no_other_active_decision(
                project_id=project_id,
                runtime_root=runtime_root,
                review_id=review_id,
                decision_id=decision_id,
            )
            review = store.read_or_none()
            if review is None:
                raise ReviewNotFound(f"Review not found: {review_id}")
            if review.status is not ReviewStatus.PENDING:
                raise ReviewDecisionConflict("Review is already resolved")
            if not secrets.compare_digest(
                review.decision_token,
                decision_token,
            ):
                raise ReviewDecisionConflict("Review decision token is stale")
            requested = {item.operation_id: item for item in decisions}
            known = {item.operation_id: item for item in review.operations}
            unknown = sorted(set(requested) - set(known))
            if unknown:
                raise ReviewDecisionError(
                    f"unknown Review operations: {unknown}",
                )
            already = sorted(
                operation_id
                for operation_id in requested
                if known[operation_id].decision
                is not ReviewOperationDecision.PENDING
            )
            if already:
                raise ReviewDecisionConflict(
                    f"Review operations already resolved: {already}",
                )

            current = self.store.read(project_id)
            rejection_changes = self._rejection_changes(
                review=review,
                decisions=decisions,
                snapshot=current,
            )
            compensation_required = bool(rejection_changes)
            timestamp = datetime.now(UTC)
            journal = ReviewDecisionJournal(
                decision_id=decision_id,
                project_id=project_id,
                review_id=review_id,
                decision_token=decision_token,
                decisions=decisions,
                state=ReviewDecisionJournalState.PREPARED,
                review_before=review,
                project_before_generation=current.generation,
                project_before_etag=current.etag,
                compensation_required=compensation_required,
                compensation_transaction_id=(
                    hashed_runtime_segment(
                        "review-transaction",
                        review_id,
                        decision_id,
                    )
                    if compensation_required
                    else None
                ),
                compensation_round_id=(
                    hashed_runtime_segment(
                        "review-decision",
                        review.round_id,
                        decision_id,
                    )
                    if compensation_required
                    else None
                ),
                created_at=timestamp,
                updated_at=timestamp,
            )
            journal_store.create(journal)

        return self._resume_decision(
            project_id=project_id,
            runtime_root=runtime_root,
            review_store=store,
            journal_store=journal_store,
            journal=journal,
        )

    @staticmethod
    def _assert_no_other_active_decision(
        *,
        project_id: str,
        runtime_root: Path,
        review_id: str,
        decision_id: str,
    ) -> None:
        transactions_root = (
            runtime_root / "reviews" / review_id / "decision-transactions"
        )
        if (
            not transactions_root.exists()
            and not transactions_root.is_symlink()
        ):
            return
        if transactions_root.is_symlink() or not transactions_root.is_dir():
            raise ReviewDecisionConflict(
                "Review decision transaction store is not a real directory",
            )
        requested_key = hashed_runtime_segment("decision", decision_id)
        for decision_root in sorted(
            transactions_root.iterdir(),
            key=lambda item: item.name,
        ):
            if decision_root.name.startswith("."):
                continue
            if decision_root.name == requested_key:
                continue
            if decision_root.is_symlink() or not decision_root.is_dir():
                raise ReviewDecisionConflict(
                    "Review decision transaction entry is not a real directory",
                )
            try:
                journal = AtomicJsonRecordStore(
                    decision_root / "journal.json",
                    ReviewDecisionJournal,
                ).read()
            except Exception as exc:
                raise ReviewDecisionConflict(
                    "Review decision journal set is inconsistent",
                ) from exc
            if (
                journal.project_id != project_id
                or journal.review_id != review_id
            ):
                raise ReviewDecisionConflict(
                    "Review decision journal identity is inconsistent",
                )
            expected_key = hashed_runtime_segment(
                "decision",
                journal.decision_id,
            )
            if decision_root.name != expected_key:
                raise ReviewDecisionConflict(
                    "Review decision journal path does not match its identity",
                )
            if journal.state is not ReviewDecisionJournalState.FINALIZED:
                raise ReviewDecisionConflict(
                    "Review already has an active decision journal: "
                    f"{journal.decision_id}",
                )

    def _resume_decision(
        self,
        *,
        project_id: str,
        runtime_root,
        review_store: AtomicJsonRecordStore[ReviewRecord],
        journal_store: AtomicJsonRecordStore[ReviewDecisionJournal],
        journal: ReviewDecisionJournal,
    ) -> ReviewRecord:
        if journal.state is ReviewDecisionJournalState.PREPARED:
            resulting: ProjectSnapshot
            if journal.compensation_required:
                resulting = self._completed_compensation_snapshot(
                    runtime_root=runtime_root,
                    journal=journal,
                )
                if resulting is None:
                    current = self.store.read(project_id)
                    if (
                        current.generation != journal.project_before_generation
                        or current.etag != journal.project_before_etag
                    ):
                        raise ReviewDecisionConflict(
                            "Project changed before the compensating decision could run",
                        )
                    rejection_changes = self._rejection_changes(
                        review=journal.review_before,
                        decisions=journal.decisions,
                        snapshot=current,
                    )
                    candidate = apply_changes(
                        current.project.model_dump(mode="json"),
                        rejection_changes,
                    )
                    result = self.commits.commit(
                        base=current,
                        candidate=candidate,
                        origin="runtime_task",
                        review_policy="auto_fix",
                        caused_by_request_id=journal.review_before.request_id,
                        caused_by_message_seq=journal.review_before.request_message_seq,
                        round_id=journal.compensation_round_id,
                        transaction_id=journal.compensation_transaction_id,
                        advance_accepted_baseline=False,
                        # The decision flow itself rewrites this Review; the
                        # compensating commit must not rebase or re-token it.
                        reconcile_exclude_round_id=journal.review_before.round_id,
                        _order_lock_held=True,
                        _lifecycle_lock_held=True,
                    )
                    resulting = result.snapshot
            else:
                resulting = self.store.read(project_id)
                if resulting.generation < journal.project_before_generation:
                    raise ReviewDecisionConflict(
                        "Project generation moved behind the prepared Review decision",
                    )
                if (
                    resulting.generation == journal.project_before_generation
                    and resulting.etag != journal.project_before_etag
                ):
                    raise ReviewDecisionConflict(
                        "Project ETag conflicts with the prepared Review decision",
                    )

            head = self._current_at_or_after(project_id, resulting)
            current_review = review_store.read_or_none()
            if current_review is None:
                raise ReviewNotFound(f"Review not found: {journal.review_id}")
            final_review = self._build_final_review(
                current=current_review,
                journal=journal,
                head=head,
            )
            timestamp = datetime.now(UTC)
            event = ReviewDecisionEvent(
                decision_id=journal.decision_id,
                review_id=journal.review_id,
                decision_token=journal.decision_token,
                decisions=journal.decisions,
                resulting_generation=resulting.generation,
                resulting_etag=resulting.etag,
                created_at=timestamp,
            )
            journal = ReviewDecisionJournal.model_validate(
                journal.model_copy(
                    update={
                        "state": ReviewDecisionJournalState.PROJECT_APPLIED,
                        "resulting_generation": resulting.generation,
                        "resulting_etag": resulting.etag,
                        "final_review": final_review,
                        "event": event,
                        "updated_at": timestamp,
                    },
                ).model_dump(mode="python"),
            )
            self._persist_project_applied(journal_store, journal)

        return self._finalize_decision(
            project_id=project_id,
            runtime_root=runtime_root,
            review_store=review_store,
            journal_store=journal_store,
            journal=journal,
        )

    def _finalize_decision(
        self,
        *,
        project_id: str,
        runtime_root,
        review_store: AtomicJsonRecordStore[ReviewRecord],
        journal_store: AtomicJsonRecordStore[ReviewDecisionJournal],
        journal: ReviewDecisionJournal,
    ) -> ReviewRecord:
        if (
            journal.state is not ReviewDecisionJournalState.PROJECT_APPLIED
            or journal.final_review is None
            or journal.event is None
            or journal.resulting_generation is None
            or journal.resulting_etag is None
        ):
            raise ReviewDecisionConflict(
                "Review decision journal is not finalizable",
            )

        current_review = review_store.read_or_none()
        if current_review is None:
            raise ReviewNotFound(f"Review not found: {journal.review_id}")
        resulting = self.store.read(project_id)
        if resulting.generation < journal.resulting_generation or (
            resulting.generation == journal.resulting_generation
            and resulting.etag != journal.resulting_etag
        ):
            raise ReviewDecisionConflict(
                "Project authority conflicts with the applied Review decision",
            )
        if current_review != journal.final_review:
            try:
                self._assert_review_can_finalize(
                    current=current_review,
                    final=journal.final_review,
                    decisions=journal.decisions,
                )
            except ReviewDecisionConflict:
                # A frontend write after the compensating Project commit is
                # authoritative.  Rebase only the Review fact onto the current
                # head; _build_final_review preserves a requested operation
                # already marked SUPERSEDED_BY_USER_EDIT and rejects any other
                # incompatible resolution.  The Project file is never touched.
                rebased = self._build_final_review(
                    current=current_review,
                    journal=journal,
                    head=resulting,
                )
                journal = ReviewDecisionJournal.model_validate(
                    journal.model_copy(
                        update={
                            "final_review": rebased,
                            "updated_at": datetime.now(UTC),
                        },
                    ).model_dump(mode="python"),
                )
                journal_store.write(journal)
            self._write_review(review_store, journal.final_review)

        self._append_decision_event_once(
            runtime_root=runtime_root,
            review_id=journal.review_id,
            event=journal.event,
        )
        self._update_state(
            project_id,
            resulting,
            resolved=journal.final_review.status is ReviewStatus.RESOLVED,
            resolved_round_id=journal.final_review.round_id,
        )
        finalized = ReviewDecisionJournal.model_validate(
            journal.model_copy(
                update={
                    "state": ReviewDecisionJournalState.FINALIZED,
                    "updated_at": datetime.now(UTC),
                },
            ).model_dump(mode="python"),
        )
        journal_store.write(finalized)
        return journal.final_review

    @staticmethod
    def _validate_idempotent_request(
        *,
        journal: ReviewDecisionJournal,
        project_id: str,
        review_id: str,
        decision_token: str,
        decisions: list[ReviewDecisionItem],
    ) -> None:
        if (
            journal.project_id != project_id
            or journal.review_id != review_id
            or not secrets.compare_digest(
                journal.decision_token,
                decision_token,
            )
            or journal.decisions != decisions
        ):
            raise ReviewDecisionConflict(
                "decision id was already used with a different Review request",
            )

    @staticmethod
    def _rejection_changes(
        *,
        review: ReviewRecord,
        decisions: list[ReviewDecisionItem],
        snapshot: ProjectSnapshot,
    ) -> list[JsonChange]:
        requested = {item.operation_id: item for item in decisions}
        known = {item.operation_id: item for item in review.operations}
        unknown = sorted(set(requested) - set(known))
        if unknown:
            raise ReviewDecisionError(f"unknown Review operations: {unknown}")
        current_data = snapshot.project.model_dump(mode="json")
        changes: list[JsonChange] = []
        for operation_id, item in requested.items():
            operation = known[operation_id]
            if operation.json_pointer is None:
                raise ReviewDecisionError(
                    "file-only Review operations are not implemented",
                )
            if item.decision != "REJECT":
                # Keep accepts the live document as-is; only a rejection must
                # prove the candidate value it is about to restore over.
                continue
            value = value_at(current_data, operation.json_pointer)
            if hash_json_value(value) != operation.after_hash:
                raise ReviewDecisionConflict(
                    f"Review candidate changed at {operation.json_pointer}",
                )
            if operation.kind.value == "create":
                restored = MISSING
                kind = "delete"
            elif operation.kind.value == "delete":
                restored = operation.before
                kind = "create"
            else:
                restored = operation.before
                kind = (
                    "reorder"
                    if operation.kind.value == "reorder"
                    else "update"
                )
            changes.append(
                JsonChange(
                    kind=kind,
                    pointer=operation.json_pointer,
                    before=value,
                    after=restored,
                ),
            )
        return changes

    def _completed_compensation_snapshot(
        self,
        *,
        runtime_root: Path,
        journal: ReviewDecisionJournal,
    ) -> ProjectSnapshot | None:
        transaction_id = journal.compensation_transaction_id
        round_id = journal.compensation_round_id
        if (
            transaction_id is None or round_id is None
        ):  # pragma: no cover - invariant
            raise ReviewDecisionConflict(
                "compensating decision has no Runtime identity",
            )
        transaction_root = runtime_root / "transactions" / transaction_id
        commit_journal = AtomicJsonRecordStore(
            transaction_root / "journal.json",
            ProjectCommitJournal,
        ).read_or_none()
        if commit_journal is None:
            return None
        if (
            commit_journal.transaction_id != transaction_id
            or commit_journal.project_id != journal.project_id
            or commit_journal.round_id != round_id
        ):
            raise ReviewDecisionConflict(
                "compensating Project transaction identity is inconsistent",
            )
        if commit_journal.state is not CommitJournalState.RUNTIME_FINALIZED:
            if commit_journal.state is CommitJournalState.ABORTED:
                raise ReviewDecisionConflict(
                    "compensating Project transaction was aborted",
                )
            raise ReviewDecisionConflict(
                "compensating Project transaction requires Runtime recovery",
            )
        if commit_journal.final_etag is None:
            raise ReviewDecisionConflict(
                "finalized compensating transaction has no final ETag",
            )
        final_project = AtomicJsonRecordStore(
            transaction_root / "final.json",
            Project,
        ).read_or_none()
        if final_project is None:
            current = self.store.read(journal.project_id)
            if current.etag != commit_journal.final_etag:
                raise ReviewDecisionConflict(
                    "compensating transaction has no verifiable final snapshot",
                )
            return current
        final_etag = project_etag(final_project)
        if (
            final_project.project_id != journal.project_id
            or final_etag != commit_journal.final_etag
        ):
            raise ReviewDecisionConflict(
                "compensating transaction final snapshot is inconsistent",
            )
        return ProjectSnapshot(
            project=final_project,
            etag=final_etag,
            generation=final_project.generation,
        )

    def _current_at_or_after(
        self,
        project_id: str,
        applied: ProjectSnapshot,
    ) -> ProjectSnapshot:
        current = self.store.read(project_id)
        if current.generation < applied.generation or (
            current.generation == applied.generation
            and current.etag != applied.etag
        ):
            raise ReviewDecisionConflict(
                "Project authority conflicts with the compensating decision",
            )
        return current

    @staticmethod
    def _build_final_review(
        *,
        current: ReviewRecord,
        journal: ReviewDecisionJournal,
        head: ProjectSnapshot,
    ) -> ReviewRecord:
        before = journal.review_before
        if (
            current.review_id != before.review_id
            or current.round_id != before.round_id
            or current.request_id != before.request_id
            or current.request_message_seq != before.request_message_seq
        ):
            raise ReviewDecisionConflict(
                "Review identity changed after decision prepare",
            )
        requested = {item.operation_id: item for item in journal.decisions}
        before_operations = {
            operation.operation_id: operation
            for operation in before.operations
        }
        current_operations = {
            operation.operation_id: operation
            for operation in current.operations
        }
        if set(before_operations) != set(current_operations):
            raise ReviewDecisionConflict(
                "Review operation set changed after decision prepare",
            )

        updated_operations = []
        for operation in current.operations:
            original = before_operations[operation.operation_id]
            for field_name in (
                "kind",
                "json_pointer",
                "file_id",
                "target_ref",
                "before_hash",
                "after_hash",
            ):
                if getattr(operation, field_name) != getattr(
                    original,
                    field_name,
                ):
                    raise ReviewDecisionConflict(
                        f"Review operation changed after decision prepare: "
                        f"{operation.operation_id}",
                    )
            item = requested.get(operation.operation_id)
            if item is None:
                updated_operations.append(operation)
                continue
            desired = (
                ReviewOperationDecision.ACCEPTED
                if item.decision == "ACCEPT"
                else ReviewOperationDecision.REJECTED
            )
            if operation.decision not in {
                ReviewOperationDecision.PENDING,
                desired,
                ReviewOperationDecision.SUPERSEDED_BY_USER_EDIT,
            }:
                raise ReviewDecisionConflict(
                    f"Review operation was resolved concurrently: "
                    f"{operation.operation_id}",
                )
            if (
                operation.decision
                is ReviewOperationDecision.SUPERSEDED_BY_USER_EDIT
            ):
                updated_operations.append(operation)
                continue
            updated_operations.append(
                operation.model_copy(update={"decision": desired}),
            )

        pending = any(
            operation.decision is ReviewOperationDecision.PENDING
            for operation in updated_operations
        )
        updated = current.model_copy(
            update={
                "candidate_generation": head.generation,
                "candidate_etag": head.etag,
                "decision_token": secrets.token_urlsafe(24),
                "status": ReviewStatus.PENDING
                if pending
                else ReviewStatus.RESOLVED,
                "operations": updated_operations,
                "updated_at": datetime.now(UTC),
            },
        )
        return ReviewRecord.model_validate(updated.model_dump(mode="python"))

    @staticmethod
    def _assert_review_can_finalize(
        *,
        current: ReviewRecord,
        final: ReviewRecord,
        decisions: list[ReviewDecisionItem],
    ) -> None:
        if (
            current.review_id != final.review_id
            or current.round_id != final.round_id
            or current.request_id != final.request_id
            or current.request_message_seq != final.request_message_seq
            or current.candidate_generation > final.candidate_generation
        ):
            raise ReviewDecisionConflict(
                "Review changed after the decision result was journaled",
            )
        requested = {item.operation_id: item for item in decisions}
        current_by_id = {
            operation.operation_id: operation
            for operation in current.operations
        }
        final_by_id = {
            operation.operation_id: operation for operation in final.operations
        }
        if set(current_by_id) != set(final_by_id):
            raise ReviewDecisionConflict(
                "Review operation set changed after the decision result was journaled",
            )
        for operation_id, current_operation in current_by_id.items():
            final_operation = final_by_id[operation_id]
            if (
                current_operation.model_copy(
                    update={"decision": final_operation.decision},
                )
                != final_operation
            ):
                raise ReviewDecisionConflict(
                    f"Review operation changed after decision result: {operation_id}",
                )
            item = requested.get(operation_id)
            if (
                item is None
                and current_operation.decision != final_operation.decision
            ):
                raise ReviewDecisionConflict(
                    f"Unrequested Review operation changed: {operation_id}",
                )
            if item is not None and current_operation.decision not in {
                ReviewOperationDecision.PENDING,
                final_operation.decision,
            }:
                raise ReviewDecisionConflict(
                    f"Review operation was resolved concurrently: {operation_id}",
                )

    @staticmethod
    def _persist_project_applied(
        store: AtomicJsonRecordStore[ReviewDecisionJournal],
        journal: ReviewDecisionJournal,
    ) -> None:
        store.write(journal)

    @staticmethod
    def _write_review(
        store: AtomicJsonRecordStore[ReviewRecord],
        review: ReviewRecord,
    ) -> None:
        store.write(review)

    @staticmethod
    def _append_decision_event_once(
        *,
        runtime_root: Path,
        review_id: str,
        event: ReviewDecisionEvent,
    ) -> None:
        store = DurableJsonlStore(
            runtime_root / "reviews" / review_id / "decisions.jsonl",
            ReviewDecisionEvent,
        )
        for existing in store.read_records():
            if existing.decision_id != event.decision_id:
                continue
            if existing != event:
                raise ReviewDecisionConflict(
                    "decision event conflicts with its durable journal",
                )
            return
        store.append(event)

    @staticmethod
    def _decision_journal_store(
        *,
        runtime_root: Path,
        review_id: str,
        decision_id: str,
    ) -> AtomicJsonRecordStore[ReviewDecisionJournal]:
        decision_key = hashed_runtime_segment("decision", decision_id)
        return AtomicJsonRecordStore(
            runtime_root
            / "reviews"
            / review_id
            / "decision-transactions"
            / decision_key
            / "journal.json",
            ReviewDecisionJournal,
        )

    def _review_store(
        self,
        project_id: str,
        review_id: str,
    ) -> AtomicJsonRecordStore[ReviewRecord]:
        try:
            review_id = require_safe_runtime_segment(
                review_id,
                label="Review id",
            )
        except RuntimeFileValidationError as exc:
            raise ReviewDecisionError(str(exc)) from exc
        return AtomicJsonRecordStore(
            self.store.project_root(project_id)
            / "runtime"
            / "reviews"
            / review_id
            / "review.json",
            ReviewRecord,
        )

    def _update_state(
        self,
        project_id: str,
        snapshot: ProjectSnapshot,
        *,
        resolved: bool,
        resolved_round_id: str | None = None,
    ) -> None:
        runtime_root = self.store.project_root(project_id) / "runtime"
        state_store = AtomicJsonRecordStore(
            runtime_root / "state.json",
            RuntimeProjectState,
        )
        state = state_store.read()
        # Multiple reviews may be pending at once (media/runtime tasks plus
        # AgentDock interventions).  Resolving one must neither drop the pointer
        # to another still-pending review nor advance the accepted baseline past
        # changes the user has not yet reviewed.
        other_pending = self._other_pending_round_id(
            project_id,
            exclude_round_id=resolved_round_id,
        )
        if not resolved:
            next_active_round_id = state.active_round_id
        elif state.active_round_id in {None, resolved_round_id}:
            next_active_round_id = other_pending
        else:
            next_active_round_id = state.active_round_id
        advance_baseline = resolved and other_pending is None
        state_store.write(
            state.model_copy(
                update={
                    "active_round_id": next_active_round_id,
                    "last_project_generation": snapshot.generation,
                    "last_project_etag": snapshot.etag,
                    "accepted_generation": (
                        snapshot.generation
                        if advance_baseline
                        else state.accepted_generation
                    ),
                    "accepted_etag": snapshot.etag
                    if advance_baseline
                    else state.accepted_etag,
                    "updated_at": datetime.now(UTC),
                },
            ),
        )

    def _other_pending_round_id(
        self,
        project_id: str,
        *,
        exclude_round_id: str | None,
    ) -> str | None:
        """Return the round id of another still-pending review, if any.

        Used to keep ``active_round_id`` pointed at a live review after a
        sibling review resolves.  The most recently updated pending review is
        preferred so the frontend surfaces the freshest work first.
        """

        reviews_root = (
            self.store.project_root(project_id) / "runtime" / "reviews"
        )
        if not reviews_root.is_dir():
            return None
        candidates: list[ReviewRecord] = []
        for child in reviews_root.iterdir():
            if child.is_symlink() or not child.is_dir():
                continue
            review = AtomicJsonRecordStore(
                child / "review.json",
                ReviewRecord,
            ).read_or_none()
            if (
                review is not None
                and review.status is ReviewStatus.PENDING
                and review.round_id != exclude_round_id
            ):
                candidates.append(review)
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.updated_at).round_id


__all__ = [
    "CreatorReviewRecoveryReport",
    "ProjectReviewRecoveryReport",
    "ProjectReviewService",
    "ReviewDecisionConflict",
    "ReviewDecisionError",
    "ReviewDecisionEvent",
    "ReviewDecisionItem",
    "ReviewDecisionRecoveryAction",
    "ReviewDecisionRecoveryOutcome",
    "ReviewNotFound",
]

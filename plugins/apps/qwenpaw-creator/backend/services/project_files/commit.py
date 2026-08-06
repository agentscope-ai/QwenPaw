# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-boolean-expressions,too-many-branches
# pylint: disable=too-many-statements
"""The generic Project commit boundary.

This is intentionally the only write primitive for ``project.json``.  It has
no content-tree CRUD methods: callers provide a real base snapshot and a
candidate object (commonly produced by jq or a typed browser patch), and the
boundary derives touched pointers, performs field-level CAS, validates the
root Pydantic model, atomically publishes it, and persists Runtime facts.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
from typing import Any, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator

from domain.enums import TransactionStatus
from services.runtime_files.atomic_store import (
    AtomicJsonRecordStore,
    fsync_directory,
)
from services.runtime_files.field_blocks import FieldBlockStore
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.manual_edit_store import ManualEditBufferStore
from services.runtime_files.path_safety import hashed_runtime_segment
from services.runtime_files.models import (
    ChangeOrigin,
    ChangeRoundRecord,
    ProjectChange,
    ProjectChangeKind,
    ReviewBoundary,
    ReviewOperation,
    ReviewOperationDecision,
    ReviewPolicy,
    ReviewRecord,
    ReviewStatus,
    RuntimeChangeSet,
    RuntimeProjectState,
    SyncStatus,
)

from .json_pointer import (
    MISSING,
    JsonCasConflict,
    JsonChange,
    diff_json,
    hash_json_value,
    merge_candidate,
    pointers_overlap,
    value_at,
)
from .locator_map import derive_ui_locator
from .models import Project
from .serialization import project_etag
from .store import ProjectSnapshot, ProjectStore

logger = logging.getLogger("qwenpaw.creator.project_files.commit")


class ProjectCommitError(RuntimeError):
    pass


class ProtectedFieldError(ProjectCommitError):
    def __init__(self, pointers: list[str]) -> None:
        super().__init__(
            "candidate modifies Runtime-protected Project fields: "
            + ", ".join(pointers),
        )
        self.pointers = pointers


class PendingProjectRecoveryError(ProjectCommitError):
    pass


class ActiveReviewConflictError(ProjectCommitError):
    """A second review boundary cannot overtake the active Review."""


class CommitJournalState(StrEnum):
    PREPARED = "PREPARED"
    PROJECT_REPLACED = "PROJECT_REPLACED"
    RUNTIME_FINALIZED = "RUNTIME_FINALIZED"
    ABORTED = "ABORTED"


class ProjectCommitJournal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    project_id: str
    # Optional only so pre-recovery journals remain parseable.  Recovery must
    # reject ``None`` instead of guessing that a custom round ID was not used.
    round_id: str | None = None
    advance_accepted_baseline: bool | None = None
    state: CommitJournalState
    base_etag: str
    candidate_etag: str
    publish_base_etag: str | None = None
    final_etag: str | None = None
    temp_path: str
    touched_pointers: list[str]
    created_at: datetime
    updated_at: datetime
    error: str | None = None

    @field_validator("transaction_id", "project_id")
    @classmethod
    def validate_required_path_ids(cls, value: str) -> str:
        return _runtime_path_segment(value)

    @field_validator("round_id")
    @classmethod
    def validate_optional_round_id(cls, value: str | None) -> str | None:
        return None if value is None else _runtime_path_segment(value)


@dataclass(frozen=True, slots=True)
class ProjectCommitResult:
    snapshot: ProjectSnapshot
    changeset: RuntimeChangeSet
    round: ChangeRoundRecord
    review: ReviewRecord | None
    transaction_id: str


PROTECTED_EXACT_POINTERS = frozenset(
    {
        "/schema_version",
        "/project_id",
        "/generation",
        "/created_at",
        "/updated_at",
    },
)
_RUNTIME_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")


def _runtime_path_segment(value: str) -> str:
    """Validate any identifier before it becomes a Runtime path segment."""

    if (
        not isinstance(value, str)
        or value in {"", ".", ".."}
        or value != value.strip()
        or not _RUNTIME_PATH_SEGMENT.fullmatch(value)
    ):
        raise ProjectCommitError(f"unsafe Runtime path identifier: {value!r}")
    return value


def _validate_same_round(
    existing: ChangeRoundRecord,
    requested: ChangeRoundRecord,
) -> None:
    """Require every transaction in one logical Round to share provenance.

    Round status and timestamps are aggregate projections and may change after
    each transaction.  Everything that identifies why/how the Round exists is
    immutable, otherwise a reused ``round_id`` could silently mix unrelated
    user requests or review boundaries.
    """

    immutable_fields = (
        "round_id",
        "project_id",
        "origin",
        "review_policy",
        "review_boundary",
        "caused_by_request_id",
        "caused_by_message_seq",
    )
    mismatched = [
        field
        for field in immutable_fields
        if getattr(existing, field) != getattr(requested, field)
    ]
    if mismatched:
        raise ProjectCommitError(
            "round id already exists with different provenance: "
            + ", ".join(mismatched),
        )


def is_protected_pointer(pointer: str) -> bool:
    return pointer in PROTECTED_EXACT_POINTERS


# Character voice bindings are tool-authoritative: only the enrollment
# executor (a Runtime task) may write them. Without this gate an agent could
# fabricate a voice_id via generic JSON editing after a failed enrollment.
_RUNTIME_ONLY_POINTER = re.compile(
    r"^/visual/entities/items/[^/]+/voice(/.*)?$",
)


def is_runtime_only_pointer(pointer: str) -> bool:
    return bool(_RUNTIME_ONLY_POINTER.match(pointer))


def _now() -> datetime:
    return datetime.now(UTC)


def _json(project: Project) -> dict[str, Any]:
    return project.model_dump(mode="json")


def _candidate_hash(candidate: Mapping[str, Any]) -> str:
    from .serialization import canonical_data, canonical_json_bytes

    import hashlib

    payload = canonical_json_bytes(canonical_data(dict(candidate)))
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _runtime_change(change: JsonChange) -> ProjectChange:
    before = None if change.before is MISSING else copy.deepcopy(change.before)
    after = None if change.after is MISSING else copy.deepcopy(change.after)
    return ProjectChange(
        kind=ProjectChangeKind(change.kind),
        json_pointer=change.pointer,
        before_hash=change.before_hash,
        after_hash=change.after_hash,
        before=before,
        after=after,
    )


def _review_operation_id(round_id: str, change: ProjectChange) -> str:
    locator = (
        f"pointer:{change.json_pointer}"
        if change.json_pointer is not None
        else f"file:{change.file_id}"
        if change.file_id is not None
        else f"target:{change.target_ref}"
    )
    return hashed_runtime_segment("operation", round_id, locator)


def _update_manual_edit_buffer(
    store: ProjectStore,
    changeset: RuntimeChangeSet,
) -> None:
    if not changeset.changes:
        return
    manual = ManualEditBufferStore(store.root)
    arguments = {
        "project_id": changeset.project_id,
        "base_generation": changeset.base_generation,
        "head_generation": changeset.final_generation,
        "changes": changeset.changes,
        "_lifecycle_lock_held": True,
    }
    if changeset.origin is ChangeOrigin.FRONTEND_EDIT:
        manual.record_frontend_commit(**arguments)
    else:
        manual.reconcile_non_frontend_commit(**arguments)


class ProjectCommitBoundary:
    def __init__(
        self,
        store: ProjectStore,
        *,
        lock_timeout_seconds: float = 10.0,
    ) -> None:
        self.store = store
        self.lock_timeout_seconds = lock_timeout_seconds

    def runtime_review_boundary(
        self,
        project_id: str,
        *,
        run_id: str,
        request_id: str | None = None,
    ) -> ReviewBoundary:
        """Build a ReviewBoundary for an autonomously generated artifact.

        Media generation (images/videos) has no originating AgentDock message,
        so the boundary anchors on the run that produced the artifact and the
        Project's current *accepted* baseline.  Anchoring on the accepted
        baseline (rather than the pre-commit generation) keeps the accepted
        pointer put while several media reviews are pending at once.
        """

        runtime_root = self.store.project_root(project_id) / "runtime"
        state = AtomicJsonRecordStore(
            runtime_root / "state.json",
            RuntimeProjectState,
        ).read_or_none()
        if state is not None:
            accepted_generation = state.accepted_generation
            accepted_etag = state.accepted_etag
        else:
            snapshot = self.store.read(project_id)
            accepted_generation = snapshot.generation
            accepted_etag = snapshot.etag
        return ReviewBoundary(
            request_message_seq=None,
            request_id=request_id,
            interrupted_run_id=run_id,
            accepted_generation=accepted_generation,
            accepted_etag=accepted_etag,
        )

    def commit(
        self,
        *,
        base: ProjectSnapshot,
        candidate: Mapping[str, Any],
        origin: ChangeOrigin | str,
        review_policy: ReviewPolicy | str = ReviewPolicy.AUTO_FIX,
        review_boundary: ReviewBoundary | None = None,
        caused_by_request_id: str | None = None,
        caused_by_message_seq: int | None = None,
        round_id: str | None = None,
        transaction_id: str | None = None,
        advance_accepted_baseline: bool = True,
        block_token: str | None = None,
        reconcile_exclude_round_id: str | None = None,
        _order_lock_held: bool = False,
        _lifecycle_lock_held: bool = False,
    ) -> ProjectCommitResult:
        if not isinstance(candidate, Mapping):
            raise ProjectCommitError(
                "Project candidate must be one JSON object",
            )
        project_id = base.project.project_id
        transaction_id = _runtime_path_segment(
            transaction_id or f"project-commit-{uuid4().hex}",
        )
        round_id = _runtime_path_segment(round_id or transaction_id)
        origin_value = ChangeOrigin(origin)
        policy_value = ReviewPolicy(review_policy)
        base_data = _json(base.project)
        candidate_data = copy.deepcopy(dict(candidate))
        candidate_etag = _candidate_hash(candidate_data)
        requested = diff_json(base_data, candidate_data)
        protected = sorted(
            {
                item.pointer
                for item in requested
                if is_protected_pointer(item.pointer)
            },
        )
        if protected:
            raise ProtectedFieldError(protected)
        if origin_value is not ChangeOrigin.RUNTIME_TASK:
            runtime_only = sorted(
                {
                    item.pointer
                    for item in requested
                    if is_runtime_only_pointer(item.pointer)
                },
            )
            if runtime_only:
                raise ProtectedFieldError(runtime_only)

        round_record = ChangeRoundRecord(
            round_id=round_id,
            project_id=project_id,
            origin=origin_value,
            review_policy=policy_value,
            review_boundary=review_boundary,
            caused_by_request_id=caused_by_request_id,
            caused_by_message_seq=caused_by_message_seq,
        )
        lifecycle_lock = (
            None
            if _lifecycle_lock_held
            else self.store.lifecycle_lock(project_id)
        )
        if lifecycle_lock is not None:
            lifecycle_lock.acquire()
        try:
            # Establish authority while the lifecycle lock is held before any
            # helper can create a path below runtime/.  A concurrent delete can
            # therefore never turn a late finalizer into a phantom Project.
            self.store.read(project_id)
            runtime_root = self.store.project_root(project_id) / "runtime"
            transaction_root = runtime_root / "transactions" / transaction_id
            if transaction_root.exists() or transaction_root.is_symlink():
                self._archive_matching_aborted_transaction(
                    transaction_root=transaction_root,
                    runtime_root=runtime_root,
                    transaction_id=transaction_id,
                    project_id=project_id,
                    round_record=round_record,
                    base_etag=base.etag,
                    candidate_etag=candidate_etag,
                    advance_accepted_baseline=advance_accepted_baseline,
                )
            aggregate_round_store = AtomicJsonRecordStore(
                runtime_root / "change-rounds" / round_id / "round.json",
                ChangeRoundRecord,
            )
            existing_aggregate_round = aggregate_round_store.read_or_none()
            if existing_aggregate_round is not None:
                _validate_same_round(existing_aggregate_round, round_record)

            timestamp = _now()
            journal = ProjectCommitJournal(
                transaction_id=transaction_id,
                project_id=project_id,
                round_id=round_id,
                advance_accepted_baseline=advance_accepted_baseline,
                state=CommitJournalState.PREPARED,
                base_etag=base.etag,
                candidate_etag=candidate_etag,
                temp_path=f"runtime/temp/project.json.{transaction_id}.tmp",
                touched_pointers=[item.pointer for item in requested],
                created_at=timestamp,
                updated_at=timestamp,
            )

            # A transaction becomes discoverable only after every recovery
            # input, including its initial PREPARED journal, is durable.  A
            # process death during preparation can leave garbage below the
            # Runtime temp staging directory, but never a journal-less transaction
            # that blocks startup recovery or later commits.
            transactions_root = transaction_root.parent
            transactions_root.mkdir(parents=True, exist_ok=True)
            staging_root = runtime_root / "temp" / "transactions"
            staging_root.mkdir(mode=0o700, exist_ok=True)
            if staging_root.is_symlink() or not staging_root.is_dir():
                raise ProjectCommitError(
                    "Project transaction staging path must be a real directory",
                )
            staged_transaction = staging_root / (
                f"{transaction_id}.{uuid4().hex}"
            )
            staged_transaction.mkdir(mode=0o700)
            try:
                AtomicJsonRecordStore(
                    staged_transaction / "round.json",
                    ChangeRoundRecord,
                ).write(round_record)
                AtomicJsonRecordStore(staged_transaction / "base.json").write(
                    base_data,
                )
                AtomicJsonRecordStore(
                    staged_transaction / "candidate.json",
                ).write(candidate_data)
                AtomicJsonRecordStore(
                    staged_transaction / "journal.json",
                    ProjectCommitJournal,
                ).write(journal)
                fsync_directory(staged_transaction)
                try:
                    os.rename(staged_transaction, transaction_root)
                except OSError as exc:
                    if (
                        transaction_root.exists()
                        or transaction_root.is_symlink()
                    ):
                        raise ProjectCommitError(
                            f"Project transaction already exists: {transaction_id}",
                        ) from exc
                    raise
                fsync_directory(transactions_root)
                fsync_directory(staging_root)
            except BaseException:
                # This is effective for ordinary failures. SIGKILL may leave
                # the temporary directory behind, but Runtime temp is outside
                # transaction admission and startup recovery scans.
                shutil.rmtree(staged_transaction, ignore_errors=True)
                raise

            transaction_round_store = AtomicJsonRecordStore(
                transaction_root / "round.json",
                ChangeRoundRecord,
            )
            journal_store = AtomicJsonRecordStore(
                transaction_root / "journal.json",
                ProjectCommitJournal,
            )
            if existing_aggregate_round is None:
                created_aggregate_round = aggregate_round_store.try_create(
                    round_record,
                )
                if created_aggregate_round is not None:
                    existing_aggregate_round = round_record
                    aggregate_round_existed = False
                else:
                    existing_aggregate_round = aggregate_round_store.read()
                    _validate_same_round(
                        existing_aggregate_round,
                        round_record,
                    )
                    aggregate_round_existed = True
            else:
                aggregate_round_existed = True
        except BaseException:
            if lifecycle_lock is not None:
                lifecycle_lock.release()
            raise

        lock_path = runtime_root / "locks" / "project-write.lock"
        # The physical Project lock remains short, but Runtime facts must be
        # finalized in the same order as Project generations are published.
        # Otherwise commit N+1 can finalize first and then be overwritten by
        # delayed state/Review writes from commit N.
        order_lock = (
            None
            if _order_lock_held
            else CrossProcessFileLock(
                runtime_root / "locks" / "project-commit-order.lock",
                timeout_seconds=self.lock_timeout_seconds,
            )
        )
        pre_publish_etag: str | None = None
        expected_final_etag: str | None = None
        try:
            if order_lock is not None:
                order_lock.acquire()
            authority = self.store.read(project_id)
            self._assert_review_admission(
                runtime_root=runtime_root,
                round_id=round_id,
                review_policy=policy_value,
            )
            self._assert_no_pending_publication(
                runtime_root=runtime_root,
                current_transaction_id=transaction_id,
                authority_etag=authority.etag,
            )
            with CrossProcessFileLock(
                lock_path,
                timeout_seconds=self.lock_timeout_seconds,
            ):
                latest = self.store.read(project_id)
                latest_data = _json(latest.project)
                merged, _requested_changes = merge_candidate(
                    base=base_data,
                    candidate=candidate_data,
                    latest=latest_data,
                )
                actual_changes = diff_json(latest_data, merged)
                if not actual_changes:
                    changeset = self._finalize_no_change(
                        latest=latest,
                        round_record=round_record,
                        runtime_root=runtime_root,
                        transaction_root=transaction_root,
                        transaction_round_store=transaction_round_store,
                        aggregate_round_store=aggregate_round_store,
                        journal_store=journal_store,
                        journal=journal,
                        advance_accepted_baseline=advance_accepted_baseline,
                    )
                    return ProjectCommitResult(
                        snapshot=latest,
                        changeset=changeset,
                        round=round_record.model_copy(
                            update={
                                "status": TransactionStatus.NO_CHANGE,
                                "updated_at": _now(),
                            },
                        ),
                        review=None,
                        transaction_id=transaction_id,
                    )

                field_blocks = FieldBlockStore(
                    runtime_root / "locks" / "fields",
                    lock_timeout_seconds=self.lock_timeout_seconds,
                )
                with field_blocks.guard_write(
                    project_id=project_id,
                    json_pointers=tuple(
                        item.pointer for item in actual_changes
                    ),
                    token=block_token,
                ):
                    merged["schema_version"] = latest_data["schema_version"]
                    merged["project_id"] = latest_data["project_id"]
                    merged["created_at"] = latest_data["created_at"]
                    merged["generation"] = latest.generation + 1
                    merged["updated_at"] = _now().isoformat()
                    final_project = Project.model_validate(merged)
                    final_data = _json(final_project)
                    pre_publish_etag = latest.etag
                    expected_final_etag = project_etag(final_project)
                    AtomicJsonRecordStore(
                        transaction_root / "latest.json",
                    ).write(
                        latest_data,
                    )
                    AtomicJsonRecordStore(
                        transaction_root / "final.json",
                    ).write(
                        final_data,
                    )
                    journal = journal.model_copy(
                        update={
                            "publish_base_etag": pre_publish_etag,
                            "final_etag": expected_final_etag,
                            "updated_at": _now(),
                        },
                    )
                    journal_store.write(journal)
                    snapshot = self.store.replace(
                        project_id,
                        final_project,
                        expected_etag=latest.etag,
                    )
                journal = journal.model_copy(
                    update={
                        "state": CommitJournalState.PROJECT_REPLACED,
                        "final_etag": snapshot.etag,
                        "updated_at": _now(),
                    },
                )
                journal_store.write(journal)

            # Runtime finalization is intentionally outside the Project write
            # lock.  A crash here is recoverable from journal + snapshots.
            # generation/updated_at and derived plan hashes are Runtime
            # bookkeeping, not user-visible ChangeSet or Review operations.
            final_changes = tuple(
                item
                for item in diff_json(latest_data, _json(snapshot.project))
                if not is_protected_pointer(item.pointer)
            )
            runtime_changes = [_runtime_change(item) for item in final_changes]
            changeset = RuntimeChangeSet(
                round_id=round_id,
                project_id=project_id,
                origin=origin_value,
                review_policy=policy_value,
                caused_by_request_id=caused_by_request_id,
                caused_by_message_seq=caused_by_message_seq,
                base_generation=latest.generation,
                final_generation=snapshot.generation,
                base_etag=latest.etag,
                final_etag=snapshot.etag,
                changes=runtime_changes,
            )
            # The immutable per-transaction ChangeSet is the recovery
            # authority.  The Round-level file is only a convenient latest
            # projection; reusing a round_id can therefore never erase the
            # evidence needed to validate an earlier journal.
            AtomicJsonRecordStore(
                transaction_root / "changeset.json",
                RuntimeChangeSet,
            ).create(changeset)
            AtomicJsonRecordStore(
                runtime_root / "change-rounds" / round_id / "changeset.json",
                RuntimeChangeSet,
            ).write(changeset)
            _update_manual_edit_buffer(self.store, changeset)
            review = self._record_review(
                runtime_root=runtime_root,
                round_record=round_record,
                snapshot=snapshot,
                changes=runtime_changes,
            )
            (
                existing_review_pending,
                existing_review_resolved,
                existing_review_round_id,
            ) = self._reconcile_existing_review(
                runtime_root=runtime_root,
                origin=origin_value,
                snapshot=snapshot,
                changes=runtime_changes,
                exclude_round_ids=frozenset(
                    value
                    for value in (
                        round_id if review is not None else None,
                        reconcile_exclude_round_id,
                    )
                    if value is not None
                ),
            )
            terminal_status = (
                TransactionStatus.PENDING_REVIEW
                if review is not None
                else TransactionStatus.COMMITTED
            )
            round_record = round_record.model_copy(
                update={"status": terminal_status, "updated_at": _now()},
            )
            transaction_round_store.write(round_record)
            aggregate_round_store.write(
                round_record.model_copy(
                    update={"created_at": existing_aggregate_round.created_at},
                ),
            )
            # Determine the active_round_id: prefer the earliest-created pending review
            if review is not None:
                reviews_root = runtime_root / "reviews"
                earliest_round_id = round_id
                earliest_created = review.created_at
                if reviews_root.is_dir():
                    for child in reviews_root.iterdir():
                        if child.is_symlink() or not child.is_dir():
                            continue
                        pending_review = AtomicJsonRecordStore(
                            child / "review.json",
                            ReviewRecord,
                        ).read_or_none()
                        if (
                            pending_review is not None
                            and pending_review.status is ReviewStatus.PENDING
                            and pending_review.created_at < earliest_created
                        ):
                            earliest_round_id = pending_review.round_id
                            earliest_created = pending_review.created_at
                active_review_round = earliest_round_id
            else:
                active_review_round = (
                    existing_review_round_id
                    if existing_review_pending
                    else None
                )
            self._update_runtime_state(
                runtime_root=runtime_root,
                snapshot=snapshot,
                accepted=(
                    existing_review_resolved
                    or (
                        review is None
                        and not existing_review_pending
                        and advance_accepted_baseline
                    )
                ),
                boundary=review_boundary,
                active_round_id=active_review_round,
            )
            journal_store.write(
                journal.model_copy(
                    update={
                        "state": CommitJournalState.RUNTIME_FINALIZED,
                        "updated_at": _now(),
                    },
                ),
            )
            logger.info(
                "project committed: project=%s transaction=%s status=%s",
                project_id,
                transaction_id,
                terminal_status.value,
            )
            return ProjectCommitResult(
                snapshot=snapshot,
                changeset=changeset,
                round=round_record,
                review=review,
                transaction_id=transaction_id,
            )
        except (JsonCasConflict, ProtectedFieldError):
            self._mark_unpublished_attempt_aborted(
                round_record=round_record,
                transaction_round_store=transaction_round_store,
                aggregate_round_store=aggregate_round_store,
                aggregate_round_existed=aggregate_round_existed,
                existing_aggregate_round=existing_aggregate_round,
            )
            journal_store.write(
                journal.model_copy(
                    update={
                        "state": CommitJournalState.ABORTED,
                        "updated_at": _now(),
                        "error": "field CAS conflict",
                    },
                ),
            )
            raise
        except BaseException as exc:
            # PROJECT_REPLACED must remain recoverable instead of being marked
            # aborted after the authority file has already changed.
            current = journal_store.read()
            if current.state is CommitJournalState.PREPARED:
                authority_etag: str | None = None
                if current.final_etag is not None:
                    try:
                        authority_etag = self.store.read(project_id).etag
                    except BaseException:
                        authority_etag = None
                if (
                    current.final_etag is not None
                    and current.final_etag != current.publish_base_etag
                    and authority_etag == current.final_etag
                ):
                    journal_store.write(
                        current.model_copy(
                            update={
                                "state": CommitJournalState.PROJECT_REPLACED,
                                "updated_at": _now(),
                                "error": f"{type(exc).__name__}: {exc}",
                            },
                        ),
                    )
                elif (
                    current.final_etag is not None
                    and current.final_etag == current.publish_base_etag
                    and authority_etag == current.final_etag
                ):
                    # A no-change transaction did not replace project.json,
                    # but its Runtime facts still need deterministic startup
                    # recovery.  Keep PREPARED instead of lying that it was
                    # unpublished/aborted.
                    journal_store.write(
                        current.model_copy(
                            update={
                                "updated_at": _now(),
                                "error": f"{type(exc).__name__}: {exc}",
                            },
                        ),
                    )
                elif (
                    current.final_etag is None
                    or authority_etag == current.publish_base_etag
                ):
                    self._mark_unpublished_attempt_aborted(
                        round_record=round_record,
                        transaction_round_store=transaction_round_store,
                        aggregate_round_store=aggregate_round_store,
                        aggregate_round_existed=aggregate_round_existed,
                        existing_aggregate_round=existing_aggregate_round,
                    )
                    journal_store.write(
                        current.model_copy(
                            update={
                                "state": CommitJournalState.ABORTED,
                                "updated_at": _now(),
                                "error": f"{type(exc).__name__}: {exc}",
                            },
                        ),
                    )
                else:
                    # The authority is neither the proven pre-publish nor the
                    # prepared final snapshot.  Keep PREPARED so startup
                    # recovery fails closed instead of lying that no publish
                    # occurred.
                    journal_store.write(
                        current.model_copy(
                            update={
                                "updated_at": _now(),
                                "error": f"{type(exc).__name__}: {exc}",
                            },
                        ),
                    )
            raise
        finally:
            if order_lock is not None:
                order_lock.release()
            if lifecycle_lock is not None:
                lifecycle_lock.release()

    @staticmethod
    def _archive_matching_aborted_transaction(
        *,
        transaction_root: Path,
        runtime_root: Path,
        transaction_id: str,
        project_id: str,
        round_record: ChangeRoundRecord,
        base_etag: str,
        candidate_etag: str,
        advance_accepted_baseline: bool,
    ) -> None:
        entry_stat = transaction_root.lstat()
        if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(
            entry_stat.st_mode,
        ):
            raise ProjectCommitError(
                f"Project transaction path is unsafe: {transaction_id}",
            )
        journal = AtomicJsonRecordStore(
            transaction_root / "journal.json",
            ProjectCommitJournal,
        ).read_or_none()
        attempt_round = AtomicJsonRecordStore(
            transaction_root / "round.json",
            ChangeRoundRecord,
        ).read_or_none()
        if journal is None or attempt_round is None:
            raise ProjectCommitError(
                f"Project transaction requires integrity recovery: {transaction_id}",
            )
        try:
            _validate_same_round(attempt_round, round_record)
        except ProjectCommitError as exc:
            raise ProjectCommitError(
                "Project transaction id was reused with different provenance: "
                f"{transaction_id}",
            ) from exc
        if (
            journal.state is not CommitJournalState.ABORTED
            or journal.transaction_id != transaction_id
            or journal.project_id != project_id
            or journal.round_id != round_record.round_id
            or journal.base_etag != base_etag
            or journal.candidate_etag != candidate_etag
            or journal.advance_accepted_baseline != advance_accepted_baseline
        ):
            raise ProjectCommitError(
                f"Project transaction already exists: {transaction_id}",
            )
        archive_root = runtime_root / "transaction-history" / "aborted"
        archive_root.mkdir(parents=True, exist_ok=True)
        archive = archive_root / f"{transaction_id}.{uuid4().hex}"
        os.rename(transaction_root, archive)
        fsync_directory(archive_root)
        fsync_directory(transaction_root.parent)

    @staticmethod
    def _mark_unpublished_attempt_aborted(
        *,
        round_record: ChangeRoundRecord,
        transaction_round_store: AtomicJsonRecordStore[ChangeRoundRecord],
        aggregate_round_store: AtomicJsonRecordStore[ChangeRoundRecord],
        aggregate_round_existed: bool,
        existing_aggregate_round: ChangeRoundRecord,
    ) -> None:
        aborted = round_record.model_copy(
            update={"status": TransactionStatus.ABORTED, "updated_at": _now()},
        )
        transaction_round_store.write(aborted)
        # A failed later transaction must not roll an already terminal logical
        # Round back to ACTIVE/ABORTED.  Only the transaction that created the
        # aggregate projection may mark that projection aborted.
        if not aggregate_round_existed:
            aggregate_round_store.write(
                aborted.model_copy(
                    update={"created_at": existing_aggregate_round.created_at},
                ),
            )

    @staticmethod
    def _assert_review_admission(
        *,
        runtime_root: Path,
        round_id: str,
        review_policy: ReviewPolicy,
    ) -> None:
        if review_policy is not ReviewPolicy.REQUIRE_REVIEW:
            return
        state = AtomicJsonRecordStore(
            runtime_root / "state.json",
            RuntimeProjectState,
        ).read_or_none()
        if (
            state is None
            or state.active_round_id is None
            or state.active_round_id == round_id
        ):
            return
        review = AtomicJsonRecordStore(
            runtime_root
            / "reviews"
            / f"review-{state.active_round_id}"
            / "review.json",
            ReviewRecord,
        ).read_or_none()
        if review is None:
            raise PendingProjectRecoveryError(
                "Runtime state references a missing active Review: "
                f"{state.active_round_id}",
            )
        # Multiple pending reviews may coexist on disk: media/runtime tasks and
        # AgentDock interventions each publish their own review round.  The read
        # path (ProjectReviewService.active) scans runtime/reviews and always
        # surfaces a still-pending review, and decisions are keyed by review id,
        # so a second review boundary no longer needs to block the first.  We
        # keep the missing-review recovery guard above, but a still-pending
        # active review is now an accepted, self-healing state.

    @staticmethod
    def _assert_no_pending_publication(
        *,
        runtime_root: Path,
        current_transaction_id: str,
        authority_etag: str,
    ) -> None:
        transactions_root = runtime_root / "transactions"
        if not transactions_root.is_dir():
            return
        for entry in sorted(
            transactions_root.iterdir(),
            key=lambda item: item.name,
        ):
            if (
                entry.name.startswith(".")
                or entry.name == current_transaction_id
                or not entry.is_dir()
            ):
                continue
            journal = AtomicJsonRecordStore(
                entry / "journal.json",
                ProjectCommitJournal,
            ).read_or_none()
            if journal is None:
                raise PendingProjectRecoveryError(
                    f"Runtime transaction has no journal: {entry.name}",
                )
            if journal.state is CommitJournalState.PROJECT_REPLACED:
                raise PendingProjectRecoveryError(
                    f"Project transaction requires recovery: {journal.transaction_id}",
                )
            if (
                journal.state is CommitJournalState.PREPARED
                and journal.final_etag is not None
                and (
                    journal.final_etag == journal.publish_base_etag
                    or authority_etag != journal.publish_base_etag
                )
            ):
                raise PendingProjectRecoveryError(
                    f"Prepared Project publication requires recovery: "
                    f"{journal.transaction_id}",
                )

    def _finalize_no_change(
        self,
        *,
        latest: ProjectSnapshot,
        round_record: ChangeRoundRecord,
        runtime_root: Path,
        transaction_root: Path,
        transaction_round_store: AtomicJsonRecordStore[ChangeRoundRecord],
        aggregate_round_store: AtomicJsonRecordStore[ChangeRoundRecord],
        journal_store: AtomicJsonRecordStore[ProjectCommitJournal],
        journal: ProjectCommitJournal,
        advance_accepted_baseline: bool,
    ) -> RuntimeChangeSet:
        latest_data = _json(latest.project)
        # Persist the exact response snapshot even when this transaction did
        # not advance Project generation.  An HTTP idempotency retry may occur
        # after unrelated later commits, so consulting the then-current
        # authority would not be enough to reconstruct the original result.
        AtomicJsonRecordStore(transaction_root / "latest.json").write(
            latest_data,
        )
        AtomicJsonRecordStore(transaction_root / "final.json").write(
            latest_data,
        )
        journal = journal.model_copy(
            update={
                "publish_base_etag": latest.etag,
                "final_etag": latest.etag,
                "updated_at": _now(),
            },
        )
        journal_store.write(journal)
        changeset = RuntimeChangeSet(
            round_id=round_record.round_id,
            project_id=round_record.project_id,
            origin=round_record.origin,
            review_policy=round_record.review_policy,
            caused_by_request_id=round_record.caused_by_request_id,
            caused_by_message_seq=round_record.caused_by_message_seq,
            base_generation=latest.generation,
            final_generation=latest.generation,
            base_etag=latest.etag,
            final_etag=latest.etag,
            changes=[],
        )
        AtomicJsonRecordStore(
            transaction_root / "changeset.json",
            RuntimeChangeSet,
        ).create(changeset)
        aggregate_round = aggregate_round_store.read()
        promote_aggregate = aggregate_round.status in {
            TransactionStatus.ACTIVE,
            TransactionStatus.ABORTED,
        }
        if promote_aggregate:
            AtomicJsonRecordStore(
                runtime_root
                / "change-rounds"
                / round_record.round_id
                / "changeset.json",
                RuntimeChangeSet,
            ).write(changeset)
        no_change_round = round_record.model_copy(
            update={
                "status": TransactionStatus.NO_CHANGE,
                "updated_at": _now(),
            },
        )
        transaction_round_store.write(no_change_round)
        if promote_aggregate:
            aggregate_round_store.write(
                no_change_round.model_copy(
                    update={"created_at": aggregate_round.created_at},
                ),
            )
        (
            pending_review,
            resolved_review,
            active_review_round,
        ) = self._reconcile_existing_review(
            runtime_root=runtime_root,
            origin=round_record.origin,
            snapshot=latest,
            changes=[],
        )
        self._update_runtime_state(
            runtime_root=runtime_root,
            snapshot=latest,
            accepted=(
                resolved_review
                or (advance_accepted_baseline and not pending_review)
            ),
            boundary=None,
            active_round_id=active_review_round if pending_review else None,
        )
        journal_store.write(
            journal.model_copy(
                update={
                    "state": CommitJournalState.RUNTIME_FINALIZED,
                    "final_etag": latest.etag,
                    "updated_at": _now(),
                },
            ),
        )
        return changeset

    def _record_review(
        self,
        *,
        runtime_root: Path,
        round_record: ChangeRoundRecord,
        snapshot: ProjectSnapshot,
        changes: list[ProjectChange],
    ) -> ReviewRecord | None:
        boundary = round_record.review_boundary
        if (
            round_record.review_policy is not ReviewPolicy.REQUIRE_REVIEW
            or boundary is None
            or not changes
        ):
            return None
        review_id = f"review-{round_record.round_id}"
        review_path = runtime_root / "reviews" / review_id / "review.json"
        store = AtomicJsonRecordStore(review_path, ReviewRecord)
        existing = store.read_or_none()
        # Resolve every locator against the committed Project so the review
        # panel can jump to the exact place a change lives (text field, or the
        # storyboard/video/character detail that produced a media artifact).
        project_data = snapshot.project.model_dump(mode="json")
        operations_by_pointer = {
            operation.json_pointer: operation
            for operation in (
                existing.operations if existing is not None else []
            )
            if operation.json_pointer is not None
        }
        for change in changes:
            pointer = change.json_pointer
            previous = (
                operations_by_pointer.get(pointer)
                if pointer is not None
                else None
            )
            operation = ReviewOperation(
                **change.model_dump(mode="python"),
                operation_id=(
                    previous.operation_id
                    if previous is not None
                    else _review_operation_id(round_record.round_id, change)
                ),
                ui_locator=(
                    previous.ui_locator
                    if previous is not None and previous.ui_locator
                    else derive_ui_locator(pointer, project_data)
                ),
            )
            if previous is not None:
                operation = operation.model_copy(
                    update={
                        "before": previous.before,
                        "before_hash": previous.before_hash,
                    },
                )
            if operation.before_hash == operation.after_hash:
                operations_by_pointer.pop(pointer, None)
            else:
                operations_by_pointer[pointer] = operation
        operations = sorted(
            operations_by_pointer.values(),
            key=lambda item: item.operation_id,
        )
        if not operations:
            if existing is not None:
                store.delete()
            return None
        review = ReviewRecord(
            review_id=review_id,
            round_id=round_record.round_id,
            request_id=boundary.request_id,
            request_message_seq=boundary.request_message_seq,
            interrupted_run_id=boundary.interrupted_run_id,
            baseline_generation=boundary.accepted_generation,
            baseline_etag=boundary.accepted_etag,
            candidate_generation=snapshot.generation,
            candidate_etag=snapshot.etag,
            decision_token=secrets.token_urlsafe(24),
            operations=operations,
            created_at=existing.created_at if existing is not None else _now(),
            updated_at=_now(),
        )
        store.write(review)
        return review

    @staticmethod
    def _reconcile_existing_review(
        *,
        runtime_root: Path,
        origin: ChangeOrigin,
        snapshot: ProjectSnapshot,
        changes: list[ProjectChange],
        exclude_round_ids: frozenset[str] = frozenset(),
    ) -> tuple[bool, bool, str | None]:
        """Keep every pending Review coherent when another accepted writer commits.

        Unrelated frontend edits remain immediately valid while a Review's
        accepted baseline stays put.  A direct user edit of a reviewed pointer
        supersedes that operation, so stale Keep/Undo can never overwrite it.
        Any other writer (an agent auto-fix or a runtime task) that touches a
        reviewed pointer rebases the operation's candidate value instead, so
        Keep/Undo always decides against the live document.  Media/runtime
        reviews and AgentDock reviews may be pending at the same time, so
        reconciliation walks all of them, not just the round that
        ``active_round_id`` happens to point at.
        """

        reviews_root = runtime_root / "reviews"
        if not reviews_root.is_dir():
            return False, False, None
        touched = [
            change.json_pointer
            for change in changes
            if change.json_pointer is not None
        ]
        current_data = snapshot.project.model_dump(mode="json")
        examined = False
        still_pending: list[ReviewRecord] = []
        for review_root in sorted(
            reviews_root.iterdir(),
            key=lambda item: item.name,
        ):
            if review_root.is_symlink() or not review_root.is_dir():
                continue
            review_store = AtomicJsonRecordStore(
                review_root / "review.json",
                ReviewRecord,
            )
            review = review_store.read_or_none()
            if review is None or review.status is not ReviewStatus.PENDING:
                continue
            if review.round_id in exclude_round_ids:
                if review.status is ReviewStatus.PENDING:
                    still_pending.append(review)
                continue
            examined = True
            operations = []
            for operation in review.operations:
                overlaps = (
                    operation.decision is ReviewOperationDecision.PENDING
                    and operation.json_pointer is not None
                    and any(
                        pointers_overlap(operation.json_pointer, pointer)
                        for pointer in touched
                    )
                )
                if overlaps and origin is ChangeOrigin.FRONTEND_EDIT:
                    operation = operation.model_copy(
                        update={
                            "decision": ReviewOperationDecision.SUPERSEDED_BY_USER_EDIT,
                        },
                    )
                elif overlaps:
                    # A non-user writer moved this pointer after the review
                    # captured it.  Rebase the candidate side so the pending
                    # operation still hashes against the live document —
                    # otherwise every later Keep/Undo would fail CAS forever.
                    live_value = value_at(
                        current_data,
                        operation.json_pointer,
                    )
                    live_hash = hash_json_value(live_value)
                    if live_hash != operation.after_hash:
                        operation = operation.model_copy(
                            update={
                                "after": None
                                if live_value is MISSING
                                else live_value,
                                "after_hash": live_hash,
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
                        "candidate_generation": snapshot.generation,
                        "candidate_etag": snapshot.etag,
                        "decision_token": secrets.token_urlsafe(24),
                        "status": ReviewStatus.PENDING
                        if pending
                        else ReviewStatus.RESOLVED,
                        "operations": operations,
                        "updated_at": _now(),
                    },
                ).model_dump(mode="python"),
            )
            review_store.write(updated)
            if pending:
                still_pending.append(updated)
        if not examined:
            return False, False, None
        if not still_pending:
            return False, True, None
        # Promote the earliest-created pending review (FIFO order).
        earliest = min(still_pending, key=lambda item: item.created_at)
        return True, False, earliest.round_id

    @staticmethod
    def _update_runtime_state(
        *,
        runtime_root: Path,
        snapshot: ProjectSnapshot,
        accepted: bool,
        boundary: ReviewBoundary | None,
        active_round_id: str | None,
    ) -> None:
        state_store = AtomicJsonRecordStore(
            runtime_root / "state.json",
            RuntimeProjectState,
        )
        existing = state_store.read_or_none()
        if existing is not None:
            if existing.last_project_generation > snapshot.generation:
                raise ProjectCommitError(
                    "Runtime Project state cannot move to an older generation",
                )
            if (
                existing.last_project_generation == snapshot.generation
                and existing.last_project_etag != snapshot.etag
            ):
                raise ProjectCommitError(
                    "Runtime Project state has a conflicting ETag at the same generation",
                )
        if accepted:
            accepted_generation = snapshot.generation
            accepted_etag = snapshot.etag
        elif boundary is not None:
            accepted_generation = boundary.accepted_generation
            accepted_etag = boundary.accepted_etag
        elif existing is not None:
            accepted_generation = existing.accepted_generation
            accepted_etag = existing.accepted_etag
        else:
            accepted_generation = snapshot.generation
            accepted_etag = snapshot.etag
        state = RuntimeProjectState(
            project_id=snapshot.project.project_id,
            active_session_id=existing.active_session_id if existing else None,
            active_goal_id=existing.active_goal_id if existing else None,
            active_round_id=active_round_id,
            last_project_generation=snapshot.generation,
            last_project_etag=snapshot.etag,
            accepted_generation=accepted_generation,
            accepted_etag=accepted_etag,
            sync_status=SyncStatus.HEALTHY,
        )
        state_store.write(state)


__all__ = [
    "ActiveReviewConflictError",
    "CommitJournalState",
    "JsonCasConflict",
    "ProjectCommitBoundary",
    "ProjectCommitError",
    "ProjectCommitJournal",
    "ProjectCommitResult",
    "ProtectedFieldError",
    "PendingProjectRecoveryError",
    "is_protected_pointer",
]

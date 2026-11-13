# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from domain.enums import TransactionStatus
from services.project_files import commit as commit_module
from services.project_files import migrations as migrations_module
from services.project_files import models as models_module
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
from services.project_files.serialization import (
    canonical_json_bytes,
    load_project_document,
)
from services.project_files.store import ProjectStore
from services.runtime_files.atomic_store import (
    AtomicJsonRecordStore,
    json_document_bytes,
)

from .conftest import (
    PROJECT_ID,
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
from .test_audio_layering import _audio_element, _project_raw


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


def _legacy_double_narration_store(tmp_path):
    """``project-1`` on disk as a pre-gate v9 doc: two enabled narrations.

    The write gate rejects two overlapping narration tracks, so this document
    is persisted directly -- exactly as a runtime predating the gate would have
    left it. Loading repairs it (mutes the older take), which is what makes
    ``base.project`` diverge from the source ``base.etag`` was hashed from:
    the crash-recovery hazard. ``audio-version-2`` is created later, so
    ``narr-new`` is the take that stays enabled.
    """

    store = ProjectStore(tmp_path.resolve())
    store.create(Project.new(project_id=PROJECT_ID, name="Initial"))
    raw = _project_raw()
    raw["project_id"] = PROJECT_ID
    raw["name"] = "Initial"
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"] = {
        "narr-old": _audio_element(
            "narr-old",
            start_tick=0,
            duration_tick=8_000,
            role="narration",
        ),
        "narr-new": _audio_element(
            "narr-new",
            start_tick=0,
            duration_tick=8_000,
            role="narration",
            version_id="audio-version-2",
        ),
    }
    versions = raw["assets"]["source_versions_by_id"]
    versions["audio-version-2"] = {
        **versions["audio-version-1"],
        "version_id": "audio-version-2",
        "logical_asset_id": "logical-audio-2",
        "created_at": "2026-09-01T08:00:00Z",
    }
    # Round-trip through the model so every defaulted field is materialized,
    # then restore the legacy both-enabled state the repair had muted. A
    # complete canonical source isolates the enabled-flip divergence: base.json
    # and the candidate then differ ONLY by that flip and the user's edit, so
    # the three-way merge stays conflict-free -- the shape of a real pre-gate
    # project, not a hand-built partial document.
    full = load_project_document(raw).model_dump(mode="json")
    full["timelines"]["items"]["timeline:main"]["elements_by_id"]["narr-old"][
        "enabled"
    ] = True
    store.project_path(PROJECT_ID).write_bytes(canonical_json_bytes(full))
    base = store.read(PROJECT_ID)
    elements = base.project.timelines.items["timeline:main"].elements_by_id
    # The load repair fired: the older take is muted in memory while the source
    # on disk still has both enabled -- the exact base.etag/base.json split.
    assert elements["narr-old"].enabled is False
    assert elements["narr-new"].enabled is True
    assert base.source_document is not None
    return store, base


def test_legacy_double_narration_prepared_unpublished_recovers(
    tmp_path,
    monkeypatch,
):
    """Window 1: rename a legacy double-narration project, then die in the
    PREPARED window before the abort journal is durable.

    ``base.json`` must be the source the ETag was hashed over -- not the
    repaired ``model_dump`` -- or recovery reports "base.json does not match
    journal base_etag" and turns a safely-abortable crash into a permanent
    integrity error.
    """

    store, base = _legacy_double_narration_store(tmp_path)
    transaction_id = "tx-legacy-unpublished"
    round_id = "round-legacy-unpublished"
    journal_path = transaction_root(store, transaction_id) / "journal.json"
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Renamed legacy project"
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

    assert (
        read_journal(store, transaction_id).state
        is CommitJournalState.PREPARED
    )
    report = recover(store)
    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.ABORTED_UNPUBLISHED
    # Aborted: the rename never published; project.json is still the legacy
    # source and still opens (re-repaired on load).
    assert store.read(PROJECT_ID).project.name == "Initial"


def test_legacy_double_narration_published_prepared_recovers(
    tmp_path,
    monkeypatch,
):
    """Window 2: the rename published but the journal stayed PREPARED.

    Recovery must prove and finalize the publication instead of leaving a
    permanent integrity error that blocks the next edit. The muted older take
    rides along in the candidate and is now persisted, so the repair becomes an
    explicit, recoverable change rather than a snapshot/ETag divergence.
    """

    store, base = _legacy_double_narration_store(tmp_path)
    transaction_id = "tx-legacy-published"
    round_id = "round-legacy-published"
    journal_path = transaction_root(store, transaction_id) / "journal.json"
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Renamed before crash"
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

    current = store.read(PROJECT_ID)
    assert current.project.name == "Renamed before crash"
    published = current.project.timelines.items["timeline:main"].elements_by_id
    assert published["narr-old"].enabled is False  # the repair persisted
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
    # Recovery cleared the pending publication, so the next edit commits
    # instead of raising PendingProjectRecoveryError.
    after = store.read(PROJECT_ID)
    next_candidate = after.project.model_dump(mode="json")
    next_candidate["description"] = "edit after recovery"
    result = ProjectCommitBoundary(store).commit(
        base=after,
        candidate=next_candidate,
        origin="runtime_task",
        transaction_id="after-recovery",
    )
    assert result.snapshot.project.description == "edit after recovery"


def test_legacy_double_narration_project_replaced_recovery_stays_consistent(
    tmp_path,
    monkeypatch,
):
    """A legacy (source != normalized) Project that dies after the Project is
    replaced must recover, rebuilding the same business ChangeSet commit
    persisted -- not one polluted by the load-time repair.

    Regression: recovery recomputed business changes from the raw
    ``latest.json``/``base.json`` source while commit used the migrated
    ``model_dump``, so the enable-flip repair surfaced as a phantom change,
    the ChangeSet disagreed with the snapshots, and a recoverable crash became
    a permanent integrity error (also on the idempotent second pass).
    """

    store, base = _legacy_double_narration_store(tmp_path)
    round_id = "round-dn-replaced"
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id="tx-dn-replaced",
        round_id=round_id,
        review=True,
    )

    first = recover(store)
    assert first.ok
    assert first.outcomes[0].action is RecoveryAction.FINALIZED_RUNTIME
    second = recover(store)
    assert second.ok
    assert second.outcomes[0].action is RecoveryAction.ALREADY_FINALIZED

    changeset = read_changeset(store, round_id)
    assert [c.json_pointer for c in changeset.changes] == ["/name"]
    review = read_review(store, round_id)
    assert [o.json_pointer for o in review.operations] == ["/name"]


def test_unnormalized_source_project_replaced_recovery_has_no_phantom_change(
    tmp_path,
    monkeypatch,
):
    """An imported Project whose source omits an optional field must recover
    with only the real user edit in its ChangeSet/Review.

    The model back-fills the missing ``script_approval_fingerprint`` on load;
    that normalization is not a user edit and must never appear as a business
    change. Same root cause as the double-narration case above: recovery must
    diff the migrated ``model_dump``, not the raw source.
    """

    store, _base = make_store(tmp_path)
    path = store.project_path(PROJECT_ID)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["settings"].pop("script_approval_fingerprint", None)
    path.write_text(json.dumps(raw), encoding="utf-8")
    base = store.read(PROJECT_ID)
    assert base.source_document != base.project.model_dump(mode="json")

    round_id = "round-approval-replaced"
    _crash_with_project_replaced(
        store,
        base,
        monkeypatch,
        transaction_id="tx-approval-replaced",
        round_id=round_id,
        review=True,
    )

    report = recover(store)
    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.FINALIZED_RUNTIME
    review = read_review(store, round_id)
    assert [o.json_pointer for o in review.operations] == ["/name"]
    changeset = read_changeset(store, round_id)
    assert [c.json_pointer for c in changeset.changes] == ["/name"]


def _enter_pre_narration_gate_runtime(monkeypatch):
    """Load/commit as the pre-gate Runtime (merge base 6e44d30) did.

    The narration self-heal and the double-voice write gate both landed after
    the merge base. A pre-upgrade Runtime therefore loaded and committed a
    legacy double-narration Project verbatim: ``base.json``,
    ``candidate.json``, ``latest.json``, ``final.json`` and the published
    ``project.json`` all kept ``narr-old.enabled=True``, and
    ``touched_pointers`` was the source diff -- just the user's rename.
    Recovery must replay that exact representation, so
    the cross-version regressions below build the transaction with both repairs
    disabled and then strip the version field the old Runtime never wrote.
    """

    monkeypatch.setattr(
        migrations_module,
        "_deconflict_overlapping_narration",
        lambda document, *, step: document,
    )
    monkeypatch.setattr(
        models_module,
        "_validate_narration_overlap",
        lambda *_args, **_kwargs: None,
    )


def _strip_diff_semantics(store, transaction_id):
    """Drop ``diff_semantics`` so the journal parses as a pre-field record.

    A base-6e44d30 journal predates the field entirely; recovery must treat an
    absent field as ``DIFF_SEMANTICS_SOURCE`` and replay the raw source diff.
    """

    path = transaction_root(store, transaction_id) / "journal.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("diff_semantics", None)
    path.write_bytes(json_document_bytes(raw))


def test_commit_stamps_migrated_diff_semantics(tmp_path):
    """A current commit records ``DIFF_SEMANTICS_MIGRATED``.

    This is the version marker that lets recovery keep diffing the migrated
    ``model_dump`` for new transactions while the cross-version tests below
    strip it to replay legacy source semantics.
    """

    store, base = make_store(tmp_path)
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Stamped"
    ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        origin="runtime_task",
        transaction_id="tx-stamp",
    )
    journal = read_journal(store, "tx-stamp")
    assert journal.diff_semantics == commit_module.DIFF_SEMANTICS_MIGRATED


def test_pre_narration_gate_finalized_transaction_recovers(
    tmp_path,
    monkeypatch,
):
    """Cross-version, completed: a pre-gate ``RUNTIME_FINALIZED`` transaction
    for a legacy double-narration Project recovers as ``ALREADY_FINALIZED``.

    The old journal recorded ``touched_pointers=['/name']`` from a source diff
    over ``base.json``/``candidate.json`` that both kept
    ``narr-old.enabled=True``. Current recovery loads ``base.json`` and
    self-heals that flag to ``False``; diffing the healed ``model_dump``
    against the raw candidate would add a phantom
    ``/timelines/.../narr-old/enabled`` and reject the journal with "journal
    touched_pointers do not match its snapshots". The absent
    ``diff_semantics`` selects the source representation so the recompute
    matches what the old Runtime wrote.
    """

    store, _base = _legacy_double_narration_store(tmp_path)
    transaction_id = "tx-xgate-finalized"
    round_id = "round-xgate-finalized"
    with monkeypatch.context() as patch:
        _enter_pre_narration_gate_runtime(patch)
        base = store.read(PROJECT_ID)
        elements = base.project.timelines.items["timeline:main"].elements_by_id
        assert elements["narr-old"].enabled is True  # no self-heal pre-gate
        candidate = base.project.model_dump(mode="json")
        candidate["name"] = "Finalized before upgrade"
        ProjectCommitBoundary(store).commit(
            base=base,
            candidate=candidate,
            transaction_id=transaction_id,
            round_id=round_id,
            **review_commit_kwargs(review_boundary(base)),
        )
    _strip_diff_semantics(store, transaction_id)
    journal = read_journal(store, transaction_id)
    assert journal.state is CommitJournalState.RUNTIME_FINALIZED
    assert journal.touched_pointers == ["/name"]
    assert journal.diff_semantics == commit_module.DIFF_SEMANTICS_SOURCE

    report = recover(store)
    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.ALREADY_FINALIZED
    assert store.read(PROJECT_ID).project.name == "Finalized before upgrade"
    # Idempotent: a second startup pass stays ALREADY_FINALIZED.
    again = recover(store)
    assert again.ok
    assert again.outcomes[0].action is RecoveryAction.ALREADY_FINALIZED


def test_pre_narration_gate_project_replaced_transaction_recovers(
    tmp_path,
    monkeypatch,
):
    """Cross-version, interrupted: a pre-gate transaction that died after the
    Project was replaced but before Review bookkeeping recovers to
    ``FINALIZED_RUNTIME``, and the next real edit commits instead of 503.

    Same source-vs-migrated divergence as above, on the ``PROJECT_REPLACED``
    path where recovery rebuilds the business ChangeSet/Review from the
    snapshots. Without the version marker the phantom ``/enabled`` made
    recovery fail, the next commit raise ``PendingProjectRecoveryError`` and a
    real rename PATCH return 503 ``STORAGE_INTEGRITY_ERROR``.
    """

    store, _base = _legacy_double_narration_store(tmp_path)
    transaction_id = "tx-xgate-replaced"
    round_id = "round-xgate-replaced"
    with monkeypatch.context() as patch:
        _enter_pre_narration_gate_runtime(patch)
        base = store.read(PROJECT_ID)
        narr_old = base.project.timelines.items["timeline:main"].elements_by_id
        assert narr_old["narr-old"].enabled is True
        _crash_with_project_replaced(
            store,
            base,
            monkeypatch,
            transaction_id=transaction_id,
            round_id=round_id,
            review=True,
        )
    _strip_diff_semantics(store, transaction_id)
    journal = read_journal(store, transaction_id)
    assert journal.state is CommitJournalState.PROJECT_REPLACED
    assert journal.touched_pointers == ["/name"]

    report = recover(store)
    assert report.ok
    assert report.outcomes[0].action is RecoveryAction.FINALIZED_RUNTIME
    changeset = read_changeset(store, round_id)
    assert [c.json_pointer for c in changeset.changes] == ["/name"]
    review = read_review(store, round_id)
    assert [o.json_pointer for o in review.operations] == ["/name"]

    # The CR's follow-up: a real rename after recovery must commit instead of
    # raising PendingProjectRecoveryError (surfaced as 503 to the API).
    after = store.read(PROJECT_ID)
    next_candidate = after.project.model_dump(mode="json")
    next_candidate["name"] = "Renamed after cross-version recovery"
    result = ProjectCommitBoundary(store).commit(
        base=after,
        candidate=next_candidate,
        origin="runtime_task",
        transaction_id="after-xgate-replaced",
    )
    assert (
        result.snapshot.project.name == "Renamed after cross-version recovery"
    )


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

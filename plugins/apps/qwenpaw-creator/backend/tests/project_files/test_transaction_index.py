# -*- coding: utf-8 -*-
"""The transaction journal index.

Two contracts, in priority order: a cached plan must never miss a transaction
that needs recovery, and the per-commit journal reads must stay bounded as
transaction history grows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.project_files.commit import ProjectCommitBoundary
from services.project_files.transaction_index import (
    INDEX_FILE_NAME,
    TransactionJournalIndex,
    drop_transaction_index,
    plan_transaction_scan,
    record_transaction_scan,
)
from services.runtime_files.atomic_store import AtomicJsonRecordStore

from .conftest import make_store

pytestmark = pytest.mark.unit


def _commit(store, base, transaction_id: str, description: str):
    candidate = base.project.model_dump(mode="json")
    candidate["description"] = description
    return ProjectCommitBoundary(store).commit(
        base=base,
        candidate=candidate,
        origin="runtime_task",
        transaction_id=transaction_id,
    )


def _read_index(transactions_root: Path) -> TransactionJournalIndex:
    return AtomicJsonRecordStore(
        transactions_root / INDEX_FILE_NAME,
        TransactionJournalIndex,
    ).read()


def _transactions_root(tmp_path) -> Path:
    root = tmp_path / "transactions"
    root.mkdir()
    return root


def _spy_journal_reads(monkeypatch) -> list[str]:
    """Record every transaction journal opened, by directory name."""

    opened: list[str] = []
    original = AtomicJsonRecordStore.read_or_none

    def spy(self):  # type: ignore[no-untyped-def]
        if self.path.name == "journal.json":
            opened.append(self.path.parent.name)
        return original(self)

    monkeypatch.setattr(AtomicJsonRecordStore, "read_or_none", spy)
    return opened


def test_each_commit_reads_only_the_transaction_still_in_flight(
    tmp_path,
    monkeypatch,
):
    # The guard used to open every journal the project ever wrote, so saving
    # got slower for the rest of the project's life. One transaction can be in
    # flight per commit, so a bounded history must mean a bounded read count.
    store, base = make_store(tmp_path)
    opened = _spy_journal_reads(monkeypatch)

    _commit(store, base, "txn-1", "first")
    assert not opened

    second = _commit(
        store,
        store.read(base.project.project_id),
        "txn-2",
        "second",
    )
    assert opened == ["txn-1"]

    before = len(opened)
    _commit(store, second.snapshot, "txn-3", "third")
    assert opened[before:] == ["txn-2"]


def test_index_records_the_transaction_in_flight_as_pending(tmp_path):
    # A commit that dies after writing PREPARED leaves the directory the next
    # commit has to find, so the in-flight id must be carried forward rather
    # than assumed settled.
    transactions_root = _transactions_root(tmp_path)
    plan = plan_transaction_scan(
        transactions_root,
        current_transaction_id="txn-9",
    )
    assert not plan.read_ids
    record_transaction_scan(transactions_root, plan, {})

    stored = _read_index(transactions_root)
    assert stored.pending == ("txn-9",)
    assert stored.directory_count == 1

    (transactions_root / "txn-9").mkdir()
    next_plan = plan_transaction_scan(
        transactions_root,
        current_transaction_id="txn-10",
    )
    assert next_plan.cached
    assert next_plan.read_ids == ("txn-9",)


def test_terminal_states_learned_by_a_scan_are_not_read_again(tmp_path):
    transactions_root = _transactions_root(tmp_path)
    for name in ("txn-1", "txn-2", "txn-3", "txn-4"):
        (transactions_root / name).mkdir()
    plan = plan_transaction_scan(
        transactions_root,
        current_transaction_id="txn-4",
    )
    assert not plan.cached
    assert plan.read_ids == ("txn-1", "txn-2", "txn-3")

    record_transaction_scan(
        transactions_root,
        plan,
        {
            "txn-1": "RUNTIME_FINALIZED",
            "txn-2": "ABORTED",
            "txn-3": "PROJECT_REPLACED",
        },
    )
    assert _read_index(transactions_root).pending == ("txn-3", "txn-4")

    # The next commit reads only what was open; settled ones stay shut.
    (transactions_root / "txn-5").mkdir()
    cached = plan_transaction_scan(
        transactions_root,
        current_transaction_id="txn-5",
    )
    assert cached.cached
    assert cached.read_ids == ("txn-3", "txn-4")


def test_an_unexpected_directory_falls_back_to_the_full_scan(tmp_path):
    # Directory count is the integrity check: a transaction appearing without a
    # commit in between (recovery, a crash, tooling) must cost a scan, never
    # hide a pending publication.
    transactions_root = _transactions_root(tmp_path)
    (transactions_root / "txn-1").mkdir()
    record_transaction_scan(
        transactions_root,
        plan_transaction_scan(
            transactions_root,
            current_transaction_id="txn-1",
        ),
        {"txn-1": "RUNTIME_FINALIZED"},
    )

    (transactions_root / "txn-stray").mkdir()
    plan = plan_transaction_scan(
        transactions_root,
        current_transaction_id="txn-2",
    )
    assert not plan.cached
    assert plan.read_ids == ("txn-1", "txn-stray")


def test_a_corrupt_index_falls_back_and_is_rebuilt(tmp_path):
    transactions_root = _transactions_root(tmp_path)
    (transactions_root / "txn-1").mkdir()
    (transactions_root / INDEX_FILE_NAME).write_text(
        "{broken",
        encoding="utf-8",
    )

    plan = plan_transaction_scan(
        transactions_root,
        current_transaction_id="txn-2",
    )
    assert not plan.cached
    record_transaction_scan(transactions_root, plan, {"txn-1": "ABORTED"})
    assert _read_index(transactions_root).pending == ("txn-2",)


def test_dropping_the_index_forces_the_next_full_scan(tmp_path):
    transactions_root = _transactions_root(tmp_path)
    for name in ("txn-1", "txn-2"):
        (transactions_root / name).mkdir()
    record_transaction_scan(
        transactions_root,
        plan_transaction_scan(
            transactions_root,
            current_transaction_id="txn-2",
        ),
        {"txn-1": "RUNTIME_FINALIZED"},
    )
    (transactions_root / "txn-3").mkdir()
    assert plan_transaction_scan(
        transactions_root,
        current_transaction_id="txn-3",
    ).cached

    # Garbage collection settles this by hand: removed directories would
    # otherwise look like the transaction a commit is expected to add.
    drop_transaction_index(transactions_root)
    plan = plan_transaction_scan(
        transactions_root,
        current_transaction_id="txn-4",
    )
    assert not plan.cached
    assert plan.read_ids == ("txn-1", "txn-2", "txn-3")


def test_replaced_directory_with_same_count_forces_full_scan(tmp_path):
    root = _transactions_root(tmp_path)
    (root / "settled").mkdir()
    (root / "in-flight").mkdir()
    plan = plan_transaction_scan(root, current_transaction_id="in-flight")
    record_transaction_scan(root, plan, {"settled": "ABORTED"})
    (root / "settled").rename(root / "unknown")
    (root / "next").mkdir()
    next_plan = plan_transaction_scan(root, current_transaction_id="next")
    assert not next_plan.cached
    assert "unknown" in next_plan.read_ids

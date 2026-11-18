# -*- coding: utf-8 -*-
"""The open-reservation ledger that keeps GC from deleting a live witness."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from services.runtime_files import idempotency_ledger

pytestmark = pytest.mark.unit


def _record(root: Path, name: str, record_id: str, status: str) -> Path:
    path = root / f"{name}.json"
    payload = {"record_id": record_id, "status": status}
    if status == "COMPLETED":
        payload["response"] = {"ok": True}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_ledger_tracks_open_reservations(tmp_path) -> None:
    root = tmp_path / "idempotency"

    assert idempotency_ledger.open_transaction_ids(root) == frozenset()

    idempotency_ledger.mark_open(root, "txn-1")
    idempotency_ledger.mark_open(root, "txn-2")
    assert idempotency_ledger.open_transaction_ids(root) == frozenset(
        {"txn-1", "txn-2"},
    )

    idempotency_ledger.mark_closed(root, "txn-1")
    assert idempotency_ledger.open_transaction_ids(root) == frozenset(
        {"txn-2"},
    )


def test_a_damaged_ledger_is_rebuilt_from_the_records(tmp_path) -> None:
    """An unreadable set is rebuilt, not trusted and not left empty.

    Trusting a partial set would delete a transaction that an IN_PROGRESS
    reservation still needs as the only durable witness for its response.
    """

    root = tmp_path / "idempotency"
    root.mkdir(parents=True)
    _record(root, "rec-open", "txn-open", "IN_PROGRESS")
    _record(root, "rec-done", "txn-done", "COMPLETED")
    ledger = root / idempotency_ledger.LEDGER_FILE_NAME
    ledger.write_text("{corrupt", encoding="utf-8")

    assert idempotency_ledger.open_transaction_ids(root) == frozenset(
        {"txn-open"},
    )
    # The rebuild is persisted, so the next sweep reads instead of scanning.
    assert "txn-open" in json.loads(ledger.read_text(encoding="utf-8"))["open"]


def test_a_failed_ledger_write_invalidates_the_file(
    tmp_path,
    monkeypatch,
) -> None:
    """A half-written ledger is worse than none, so it is dropped instead.

    The reservation the failed write would have recorded is lost from the set,
    which is exactly the dangerous direction -- so the file is invalidated and
    the next reader rebuilds from the records themselves.
    """

    root = tmp_path / "idempotency"
    root.mkdir(parents=True)
    _record(root, "rec", "txn-open", "IN_PROGRESS")

    def boom(*_args, **_kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(idempotency_ledger.os, "replace", boom)
    idempotency_ledger.mark_open(root, "txn-new")  # must not raise
    monkeypatch.undo()

    assert idempotency_ledger.open_transaction_ids(root) == frozenset(
        {"txn-open"},
    )


def test_an_unreadable_record_is_still_treated_as_open(tmp_path) -> None:
    """Fail toward keeping: a damaged head cannot prove the request settled."""

    root = tmp_path / "idempotency"
    root.mkdir(parents=True)
    (root / "rec.json").write_bytes(
        b'{"record_id": "txn-mangled", "status": "IN_PROGRESS"',
    )

    assert idempotency_ledger.open_transaction_ids(root) == frozenset(
        {"rec"},
    )


def test_mark_open_serializes_the_shared_load_modify_save(
    tmp_path,
    monkeypatch,
) -> None:
    """Two reservations for different keys must both survive.

    Regression for review #243 P1: ``mark_open`` is called under each
    caller's per-key idempotency lock, so two concurrent writes for
    different keys do not overlap there -- but they do overlap on the
    single shared ledger file. Without a further lock, thread A loads the
    empty set, pauses, thread B loads the same empty set and publishes
    ``{B}``, then A's write clobbers B. A lost id means GC treats that
    transaction as unprotected and deletes the durable witness an
    IN_PROGRESS reservation still needs to replay its response.
    """

    root = tmp_path / "idempotency"
    root.mkdir(parents=True)

    inside_a = threading.Event()
    leave_a = threading.Event()
    real_read = idempotency_ledger._read_ledger

    def pausing_read(path_root: Path) -> dict[str, str] | None:
        result = real_read(path_root)
        # Only thread A's first read is delayed; when A resumes and
        # releases the lock, thread B enters and its read must see A's
        # already-published entry -- proof the shared update was actually
        # serialized rather than lucky scheduling.
        if not inside_a.is_set():
            inside_a.set()
            leave_a.wait(timeout=5)
        return result

    monkeypatch.setattr(idempotency_ledger, "_read_ledger", pausing_read)

    b_finished = threading.Event()

    def thread_a() -> None:
        idempotency_ledger.mark_open(root, "txn-A")

    def thread_b() -> None:
        inside_a.wait(timeout=5)
        idempotency_ledger.mark_open(root, "txn-B")
        b_finished.set()

    ta = threading.Thread(target=thread_a)
    tb = threading.Thread(target=thread_b)
    ta.start()
    assert inside_a.wait(timeout=5)
    tb.start()
    # Give B a window to bypass the lock if it were unprotected. Without
    # the lock it would finish here and A's later write would drop its
    # entry; with the lock, B is blocked in acquire.
    time.sleep(0.2)
    assert not b_finished.is_set(), (
        "thread B completed while A was inside mark_open -- "
        "the shared load-modify-save is not serialized"
    )
    leave_a.set()
    ta.join(timeout=5)
    tb.join(timeout=5)

    assert idempotency_ledger.open_transaction_ids(root) == frozenset(
        {"txn-A", "txn-B"},
    )


def test_mark_closed_waits_for_the_in_flight_mark_open(
    tmp_path,
    monkeypatch,
) -> None:
    """A settle that raced past its own add still removes the entry.

    Without the shared lock, ``mark_closed`` would read an empty ledger
    (A had not written yet), silently return, and A's write would leave
    ``txn-A`` behind forever -- GC would then treat the settled
    transaction as an open witness and never reclaim it.
    """

    root = tmp_path / "idempotency"
    root.mkdir(parents=True)

    inside_a = threading.Event()
    leave_a = threading.Event()
    real_read = idempotency_ledger._read_ledger

    def pausing_read(path_root: Path) -> dict[str, str] | None:
        result = real_read(path_root)
        if not inside_a.is_set():
            inside_a.set()
            leave_a.wait(timeout=5)
        return result

    monkeypatch.setattr(idempotency_ledger, "_read_ledger", pausing_read)

    def thread_a() -> None:
        idempotency_ledger.mark_open(root, "txn-A")

    def thread_b() -> None:
        inside_a.wait(timeout=5)
        idempotency_ledger.mark_closed(root, "txn-A")

    ta = threading.Thread(target=thread_a)
    tb = threading.Thread(target=thread_b)
    ta.start()
    assert inside_a.wait(timeout=5)
    tb.start()
    leave_a.set()
    ta.join(timeout=5)
    tb.join(timeout=5)

    # With the lock, B entered after A had written {txn-A}, found the
    # id there and popped it. The file remains as an empty ledger rather
    # than being recreated by a later scan.
    assert idempotency_ledger.open_transaction_ids(root) == frozenset()

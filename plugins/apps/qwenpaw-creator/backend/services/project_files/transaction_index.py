# -*- coding: utf-8 -*-
"""Which Project transactions still need a journal read.

Every commit asks the same question before it may publish: does another
transaction still sit in a state that requires recovery?  Answering it by
reading ``journal.json`` of every transaction directory ever written made the
check cost grow with project history (observed: 242 directories and 72 ms per
save, on the hot path of every keystroke-triggered patch).

The answer only ever needs the transactions that are *not* terminal.  Journal
states move forward and never return -- ``PREPARED`` -> ``PROJECT_REPLACED`` ->
``RUNTIME_FINALIZED`` / ``ABORTED`` -- so a directory recorded as terminal is
terminal forever, and the handful of ids still in flight are the only ones
worth opening.  Those ids are cached in ``transactions/.journal-index.json``.

The cache is an optimization, never a source of truth:

* It is validated against a fresh directory listing on every commit, and any
  disagreement (an unexpected directory count, an unknown id, a corrupt or
  absent file) falls back to the full scan and rebuilds the index.
* It is only written *after* a scan completed without raising, so an aborted
  commit simply re-reads those journals next time.

Both failure modes cost a scan; neither can hide a transaction that needs
recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

from services.runtime_files.atomic_store import AtomicJsonRecordStore

logger = logging.getLogger("qwenpaw.creator.project_files.transaction_index")

INDEX_FILE_NAME = ".journal-index.json"
INDEX_VERSION = 2

# Journal states that can never be revisited.  Kept as strings so this module
# does not import the commit boundary that defines the enum.
TERMINAL_JOURNAL_STATES = frozenset({"RUNTIME_FINALIZED", "ABORTED"})


class TransactionJournalIndex(BaseModel):
    """The cached answer for one ``runtime/transactions`` directory.

    ``directory_count`` is the number of transaction directories seen when the
    index was written, *including* the transaction that was then in flight.  A
    commit creates exactly one directory, so the next commit expects
    ``directory_count + 1``; anything else means the listing and the cache
    disagree and the full scan runs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = INDEX_VERSION
    directory_count: int = Field(default=0, ge=0)
    directory_digest: str = ""
    pending: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransactionScanPlan:
    """What ``_assert_no_pending_publication`` should open, and why.

    ``read_ids`` never contains ``current_transaction_id``: its own
    ``PREPARED`` journal is expected and is not evidence against it. It does
    land in the next index as pending, because a commit that dies after that
    journal leaves behind exactly the directory the next commit has to find.
    """

    directory_count: int
    directory_digest: str
    read_ids: tuple[str, ...]
    current_transaction_id: str
    cached: bool


def _index_store(transactions_root: Path) -> AtomicJsonRecordStore:
    # Dot-prefixed names are excluded from the listing, so the index cannot be
    # mistaken for a transaction.
    return AtomicJsonRecordStore(
        transactions_root / INDEX_FILE_NAME,
        TransactionJournalIndex,
    )


def list_transaction_ids(
    transactions_root: Path,
    *,
    exclude: str | None = None,
) -> tuple[str, ...]:
    """Transaction directory names, sorted, excluding staging and the index."""
    if not transactions_root.is_dir():
        return ()
    names = [
        entry.name
        for entry in transactions_root.iterdir()
        if not entry.name.startswith(".")
        and entry.is_dir()
        and entry.name != exclude
    ]
    return tuple(sorted(names))


def _read_stored_index(
    transactions_root: Path,
) -> TransactionJournalIndex | None:
    try:
        stored = _index_store(transactions_root).read_or_none()
    except Exception as error:  # noqa: BLE001 - any bad cache means "rescan"
        logger.warning(
            "transaction journal index unreadable; scanning in full: %s",
            error,
        )
        return None
    if stored is None or stored.version != INDEX_VERSION:
        return None
    return stored


def _directory_digest(names: tuple[str, ...]) -> str:
    return hashlib.sha256(
        b"\0".join(os.fsencode(name) for name in names)
    ).hexdigest()


def plan_transaction_scan(
    transactions_root: Path,
    *,
    current_transaction_id: str,
) -> TransactionScanPlan:
    """Decide which journals must be read for the transaction in flight.

    The current transaction is never inspected (its own ``PREPARED`` journal is
    not evidence against itself), so it is dropped from the listing first.  A
    commit creates exactly one directory, which is the one just excluded: the
    remaining count has to equal what the cached index recorded.
    """
    other_ids = list_transaction_ids(
        transactions_root,
        exclude=current_transaction_id,
    )
    stored = (
        _read_stored_index(transactions_root)
        if transactions_root.is_dir()
        else None
    )
    directory_digest = _directory_digest(
        tuple(sorted((*other_ids, current_transaction_id)))
    )
    if (
        stored is not None
        and stored.directory_count == len(other_ids)
        and stored.directory_digest == _directory_digest(other_ids)
    ):
        known = set(other_ids)
        known.add(current_transaction_id)
        if all(name in known for name in stored.pending):
            return TransactionScanPlan(
                directory_count=len(other_ids) + 1,
                directory_digest=directory_digest,
                read_ids=stored.pending,
                current_transaction_id=current_transaction_id,
                cached=True,
            )
    return TransactionScanPlan(
        directory_count=len(other_ids) + 1,
        directory_digest=directory_digest,
        read_ids=other_ids,
        current_transaction_id=current_transaction_id,
        cached=False,
    )


def record_transaction_scan(
    transactions_root: Path,
    plan: TransactionScanPlan,
    states: Mapping[str, str],
) -> None:
    """Persist what the scan learned, once the commit may proceed.

    ``states`` covers only the journals that were read.  On a cached plan the
    unread directories are terminal by the index's own invariant, so they are
    correctly absent from ``pending``; on a full plan everything was read.  The
    transaction in flight is always carried forward as pending.
    """
    pending = tuple(
        sorted(
            {
                name
                for name, state in states.items()
                if state not in TERMINAL_JOURNAL_STATES
            }
            | {plan.current_transaction_id},
        ),
    )
    try:
        _index_store(transactions_root).write(
            TransactionJournalIndex(
                version=INDEX_VERSION,
                directory_count=plan.directory_count,
                directory_digest=plan.directory_digest,
                pending=pending,
            ),
        )
    except Exception as error:  # noqa: BLE001 - a lost cache only costs a scan
        logger.warning(
            "transaction journal index could not be written: %s",
            error,
        )


def drop_transaction_index(transactions_root: Path) -> None:
    """Invalidate the cache after transaction directories were removed.

    Garbage collection changes the directory count without a commit in
    between, so the next commit must not trust the previous listing.
    """
    try:
        (transactions_root / INDEX_FILE_NAME).unlink(missing_ok=True)
    except OSError as error:  # pragma: no cover - defensive
        logger.warning(
            "transaction journal index could not be dropped: %s",
            error,
        )

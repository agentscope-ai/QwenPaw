# -*- coding: utf-8 -*-
"""Measure and explicitly reclaim settled transactions, retaining recent receipts."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from uuid import uuid4

from services.media_files.task_scratch import (
    history_reclaim_kept,
)
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files import idempotency_ledger
from services.runtime_files.models import IdempotencyRecord, IdempotencyStatus
from services.runtime_files.path_safety import is_link_path

from .transaction_index import drop_transaction_index

logger = logging.getLogger("qwenpaw.creator.project_files.transaction_gc")

# Terminal transactions kept after a sweep, newest first by directory mtime.
TERMINAL_TRANSACTION_RETENTION = 50

TRANSACTIONS_DIR_NAME = "transactions"
JOURNAL_FILE_NAME = "journal.json"
# A reclaimed transaction is renamed under this prefix before deletion, so
# the commit scan never observes a half-deleted directory. Leading dot keeps
# it out of ``list_transaction_ids`` and the surplus enumerator.
TOMBSTONE_PREFIX = ".deleted-"

# The only states this module will delete. Anything else -- including a state
# this build does not know yet -- is preserved.
TERMINAL_JOURNAL_STATES = frozenset({"RUNTIME_FINALIZED", "ABORTED"})

_DISABLED_VALUES = frozenset({"0", "false", "no", "off"})


def transaction_gc_enabled() -> bool:
    """Whether terminal transactions may be collected; on unless switched off.

    Deleting commit history needs an emergency stop that does not require a
    release: one env var restores the previous keep-forever behaviour.
    """

    raw = os.environ.get("CREATOR_TRANSACTION_GC_ENABLED", "")
    return raw.strip().casefold() not in _DISABLED_VALUES


def _journal_state(transaction_dir: Path) -> str | None:
    """The journal's ``state`` string, or None when it cannot be trusted."""

    try:
        stored = AtomicJsonRecordStore(
            transaction_dir / JOURNAL_FILE_NAME,
            None,
        ).read_or_none()
    except (
        Exception
    ):  # noqa: BLE001 - corrupt, unreadable, locked: all mean keep
        return None
    if not isinstance(stored, dict):
        return None
    state = stored.get("state")
    return state if isinstance(state, str) else None


def _directory_bytes(transaction_dir: Path) -> int:
    total = 0
    for path in transaction_dir.rglob("*"):
        try:
            if path.is_file() and not is_link_path(path):
                total += path.stat().st_size
        except OSError:  # pragma: no cover - a vanishing file is not a loss
            continue
    return total


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _eligible(entry: Path) -> bool:
    """An unreadable or unfinished transaction is retained."""
    if (
        entry.name.startswith(".")
        or not entry.is_dir()
        or is_link_path(entry)
        or is_link_path(entry / JOURNAL_FILE_NAME)
    ):
        return False
    return _journal_state(entry) in TERMINAL_JOURNAL_STATES


def _eligible_candidates(
    transactions_root: Path,
) -> list[tuple[float, Path, int]]:
    """Settled transaction directories with their mtime and byte size."""

    candidates: list[tuple[float, Path, int]] = []
    for entry in transactions_root.iterdir():
        if not _eligible(entry):
            continue
        candidates.append((_mtime(entry), entry, _directory_bytes(entry)))
    return candidates


def _open_reservation_ids(
    transactions_root: Path, *, verify: bool
) -> frozenset[str] | None:
    """A storage estimate can use the ledger. Removal verifies the records."""
    root = transactions_root.parent / "commands" / "idempotency"
    if is_link_path(root.parent) or is_link_path(root):
        return None
    if not root.exists():
        return frozenset()
    if not verify:
        return idempotency_ledger.open_transaction_ids(root)
    protected = set()
    try:
        for path in root.iterdir():
            if (
                path.suffix != ".json"
                or path.name == idempotency_ledger.LEDGER_FILE_NAME
            ):
                continue
            if not path.is_file() or is_link_path(path):
                return None
            record = IdempotencyRecord.model_validate_json(path.read_bytes())
            if record.status is IdempotencyStatus.IN_PROGRESS:
                protected.add(record.record_id)
    except (OSError, ValueError):
        logger.warning(
            "Unresolved idempotency records; keeping transactions in %s", root
        )
        return None
    return frozenset(protected)


def _surplus_candidates(
    transactions_root: Path,
    retention: int,
    protected: frozenset[str] | None = frozenset(),
) -> list[tuple[float, Path, int]]:
    """Exactly what a sweep would remove: the newest ``retention`` stay.

    Both the storage profile and the collector must answer from this one
    ordering. The delete loop keeps the newest by mtime, so a profile that
    truncated the raw directory listing instead reported a different set: the
    home page then showed a pending size under the cap with no way to confirm
    it, while the real sweep stopped on a surplus above that cap.

    Protected transactions are dropped before the cut, so they neither get
    deleted nor consume one of the retained slots.
    """

    if protected is None:
        return []
    candidates = _eligible_candidates(transactions_root)
    if protected:
        candidates = [
            item for item in candidates if item[1].name not in protected
        ]
    if len(candidates) <= retention:
        return []
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[retention:]


def surplus_transaction_bytes(
    project_root: Path,
    *,
    retention: int = TERMINAL_TRANSACTION_RETENTION,
) -> int:
    """What a sweep would reclaim below one Project, without touching it.

    The storage profile answers "how much is waiting for my confirmation" with
    this; computing it by deleting would be a poor way to ask.
    """

    transactions_root = Path(project_root) / "runtime" / TRANSACTIONS_DIR_NAME
    if (
        any(
            is_link_path(path)
            for path in (
                project_root,
                transactions_root.parent,
                transactions_root,
            )
        )
        or not transactions_root.is_dir()
    ):
        return 0
    if history_reclaim_kept(project_root) or not transaction_gc_enabled():
        return 0
    surplus = _surplus_candidates(
        transactions_root,
        retention,
        _open_reservation_ids(transactions_root, verify=False),
    )
    return sum(size for _mtime_value, _entry, size in surplus)


def _atomic_reclaim(entry: Path) -> tuple[bool, bool]:
    """Move one transaction directory to a hidden tombstone, then delete.

    Returns ``(hidden_from_scan, fully_removed)``. The rename is atomic
    within the same filesystem, so once it succeeds the original path is
    gone from the commit scan's view no matter what follows --
    ``hidden_from_scan`` is True and correctness (the scan never sees a
    half-deleted transaction) is guaranteed. ``fully_removed`` reports
    whether the bytes actually left the disk, which the caller uses so a
    partial delete is never counted as reclaimed space.

    The tombstone name starts with a dot so ``list_transaction_ids`` and
    the surplus enumerator skip it by their existing rule; a leftover
    from an interrupted ``rmtree`` here is reclaimed by
    :func:`_purge_tombstones` on the next sweep, not by the
    journal-based path (the journal is the first thing that delete
    removes, so it can never qualify again). On rename failure the original is retained.
    """

    tombstone = entry.with_name(
        f"{TOMBSTONE_PREFIX}{entry.name}-{uuid4().hex}"
    )
    try:
        os.rename(entry, tombstone)
    except OSError as exc:
        logger.warning("Transaction is still in use: %s (%s)", entry, exc)
        return False, False
    shutil.rmtree(tombstone, ignore_errors=True)
    if tombstone.exists():
        # Out of the scan's view (correct), but the disk is not yet
        # reclaimed; _purge_tombstones finishes it on the next sweep.
        logger.warning(
            "transaction tombstone cleanup deferred to next sweep: %s",
            tombstone,
        )
        return (True, False)
    return (True, True)


def _purge_tombstones(transactions_root: Path) -> tuple[int, int]:
    """Delete leftover ``.deleted-*`` tombstones; return (count, bytes).

    Review #243 r4548690102 follow-up: ``_atomic_reclaim`` renames a
    transaction to a tombstone and then ``rmtree``s it, but that delete
    can be interrupted part-way -- journal gone first, a large snapshot
    file left behind. Such a tombstone is invisible to the journal-based
    eligibility check (its journal no longer exists, so it never reads
    as terminal), so the old "the next sweep picks it up" comment had no
    code behind it and the bytes leaked forever. Purging by name is
    idempotent and independent of content: any surviving
    ``.deleted-*`` directory is, by construction, already moved out of
    the scan's view and safe to remove.
    """

    purged = 0
    freed_bytes = 0
    for tombstone in transactions_root.glob(TOMBSTONE_PREFIX + "*"):
        if not tombstone.is_dir() or is_link_path(tombstone):
            continue
        size = _directory_bytes(tombstone)
        shutil.rmtree(tombstone, ignore_errors=True)
        if tombstone.exists():
            logger.warning(
                "transaction tombstone still present after purge: %s",
                tombstone,
            )
            continue
        purged += 1
        freed_bytes += size
    return (purged, freed_bytes)


def collect_project_transactions(
    project_root: Path,
    *,
    retention: int = TERMINAL_TRANSACTION_RETENTION,
    confirmed: bool = False,
) -> tuple[int, int]:
    """Reclaim a single explicitly confirmed project and return actual counts."""

    if (
        not confirmed
        or not transaction_gc_enabled()
        or history_reclaim_kept(project_root)
    ):
        return (0, 0)
    transactions_root = Path(project_root) / "runtime" / TRANSACTIONS_DIR_NAME
    if (
        any(
            is_link_path(path)
            for path in (
                project_root,
                transactions_root.parent,
                transactions_root,
            )
        )
        or not transactions_root.is_dir()
    ):
        return (0, 0)
    # Finish any tombstone an earlier sweep renamed but could not fully
    # delete, independent of the journal-based eligibility below -- the
    # bytes it holds are already out of the scan's view and this is the
    # only path that can ever reclaim them (review #243 r4548690102).
    purged, purged_bytes = _purge_tombstones(transactions_root)
    surplus = _surplus_candidates(
        transactions_root,
        retention,
        _open_reservation_ids(transactions_root, verify=True),
    )
    if not surplus:
        return (purged, purged_bytes)
    removed = 0
    removed_bytes = 0
    for _mtime_value, entry, size in surplus:
        # ``shutil.rmtree`` is not atomic: the journal disappears first and
        # the directory is rmdired last, so a commit scan that already
        # captured this name in ``list_transaction_ids`` can see
        # "directory still here, journal already gone" and raise a false
        # ``PendingProjectRecoveryError`` on the intermediate state
        # (review #243 r4548690102 follow-up). Renaming to a
        # dot-prefixed tombstone is a single atomic operation, so the
        # scan sees either the fully intact transaction or nothing at
        # all -- ``list_transaction_ids`` skips leading-dot entries and
        # ``entry.lstat`` on the original name raises FileNotFoundError.
        # Then, and only then, do we rmtree the moved tree.
        hidden, fully_removed = _atomic_reclaim(entry)
        if not hidden:
            # Still where the scan looks: reclaiming it here would be
            # pointless, and counting it would be a lie. Try again next
            # sweep.
            continue
        # ``removed`` counts transactions moved out of the retained set
        # (correctness: the scan no longer sees them); ``removed_bytes``
        # only counts space actually released from disk. A renamed-but-
        # not-yet-deleted tombstone is removed without releasing bytes
        # this round -- _purge_tombstones reclaims them next sweep, so
        # neither count is inflated and nothing leaks (review #243
        # r4548690102 follow-up).
        removed += 1
        if fully_removed:
            removed_bytes += size
    if removed:
        # The listing the commit path cached no longer matches the directory.
        drop_transaction_index(transactions_root)
    return (removed + purged, removed_bytes + purged_bytes)

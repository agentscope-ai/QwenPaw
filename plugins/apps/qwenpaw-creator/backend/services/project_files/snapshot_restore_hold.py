# -*- coding: utf-8 -*-
"""Process-local one-shot marks for timelines the user rolled back.

The auto-snapshot dedupe window assumes the newest auto-snapshot is the
baseline of the current editing session, so one session leaves one
pre-session copy instead of one copy per commit.  Applying a snapshot
breaks that assumption: the live content jumps to an older version, and
the newest auto-snapshot now describes a branch the user just abandoned.
Without a mark the next agent write inside the window would land on the
rolled-back state with nothing frozen behind it.

One mark is settled by exactly one *published* auto-snapshot, so a
rollback forces a single fresh baseline rather than reopening the window
for every following commit. Reading a mark never clears it: a commit can
still fail on CAS or validation after the auto-snapshot pass, and the
agent's retry must land the baseline.

Single-process deployment is a hard premise, so the registry is
in-memory only.  A restart drops the marks, which merely returns the
timeline to normal window behaviour — the applied snapshot itself stays
in the project and remains re-appliable.
"""

from __future__ import annotations

import threading
from typing import Iterable

_lock = threading.Lock()
# (project_id, timeline_id) pending one forced auto-snapshot.
_marks: set[tuple[str, str]] = set()


def note_snapshot_restore(
    project_id: str,
    timeline_ids: Iterable[str],
) -> None:
    """Record that *timeline_ids* were rolled back to a snapshot."""
    ids = [timeline_id for timeline_id in timeline_ids if timeline_id]
    if not ids:
        return
    with _lock:
        for timeline_id in ids:
            _marks.add((project_id, timeline_id))


def is_restore_pending(project_id: str, timeline_id: str) -> bool:
    """Whether *timeline_id* still owes a post-rollback baseline."""
    with _lock:
        return (project_id, timeline_id) in _marks


def settle_snapshot_restore(
    project_id: str,
    timeline_ids: Iterable[str],
) -> None:
    """Clear marks whose forced baseline is now durably published.

    Called after a successful commit, never at decision time: a mark
    consumed by an attempt that then failed CAS would leave the agent's
    retry with no baseline at all — exactly the gap this registry closes.
    """
    with _lock:
        for timeline_id in timeline_ids:
            _marks.discard((project_id, timeline_id))


def clear(project_id: str | None = None) -> None:
    """Drop marks for one project (delete/close) or all (tests)."""
    with _lock:
        if project_id is None:
            _marks.clear()
            return
        for key in [key for key in _marks if key[0] == project_id]:
            _marks.remove(key)


__all__ = [
    "clear",
    "is_restore_pending",
    "note_snapshot_restore",
    "settle_snapshot_restore",
]

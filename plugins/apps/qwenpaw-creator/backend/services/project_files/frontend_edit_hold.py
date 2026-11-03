# -*- coding: utf-8 -*-
"""Process-local grace registry for auto-saved frontend element edits.

The workbench persists drafts automatically at field boundaries (blur,
navigation, regenerate), so a frontend commit no longer means "the user
finished authoring". For unattended projects the work scheduler
dispatches READY media nodes on every commit wake; without a grace
window a half-finished prompt could be sent to a paid provider the
moment the user tabs away. Every frontend PATCH records its affected
elements here and the scheduler skips their nodes until the window
expires. Manual dispatch through the work-graph API (the 再次生成
button) stays untouched — a human click is an explicit instruction.

Single-process deployment is a hard premise, so the registry is
in-memory only: a restart clears it, which merely re-enables automatic
dispatch of already-persisted state.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Iterable

FRONTEND_EDIT_GRACE_SECONDS = 20.0

_ELEMENT_POINTER = re.compile(
    r"^/timelines/items/[^/]+/elements_by_id/([^/]+)",
)

_lock = threading.Lock()
# (project_id, element_id) -> monotonic deadline.
_holds: dict[tuple[str, str], float] = {}


def element_ids_from_pointers(pointers: Iterable[str]) -> set[str]:
    """Element ids named by RFC 6901 pointers of one committed changeset."""
    ids: set[str] = set()
    for pointer in pointers:
        match = _ELEMENT_POINTER.match(pointer or "")
        if match:
            ids.add(match.group(1))
    return ids


def note_frontend_edit(
    project_id: str,
    element_ids: Iterable[str],
    *,
    now: float | None = None,
) -> None:
    """Open (or extend) the dispatch grace window for edited elements."""
    ids = [element_id for element_id in element_ids if element_id]
    if not ids:
        return
    current = time.monotonic() if now is None else now
    deadline = current + FRONTEND_EDIT_GRACE_SECONDS
    with _lock:
        for element_id in ids:
            _holds[(project_id, element_id)] = deadline


def hold_remaining(
    project_id: str,
    element_id: str,
    *,
    now: float | None = None,
) -> float:
    """Seconds left in the grace window; 0 when expired or absent."""
    current = time.monotonic() if now is None else now
    key = (project_id, element_id)
    with _lock:
        deadline = _holds.get(key)
        if deadline is None:
            return 0.0
        if deadline <= current:
            del _holds[key]
            return 0.0
        return deadline - current


def clear(project_id: str | None = None) -> None:
    """Drop holds for one project (delete/close) or all (tests)."""
    with _lock:
        if project_id is None:
            _holds.clear()
            return
        for key in [key for key in _holds if key[0] == project_id]:
            del _holds[key]


__all__ = [
    "FRONTEND_EDIT_GRACE_SECONDS",
    "clear",
    "element_ids_from_pointers",
    "hold_remaining",
    "note_frontend_edit",
]

# -*- coding: utf-8 -*-
"""Exact, ordered hunk matching with diagnostics and no fuzzy mutation."""

from __future__ import annotations

from .models import PatchConflict, PatchHunk


def _candidate_positions(
    lines: list[str],
    needle: tuple[str, ...],
    start: int,
) -> list[int]:
    if not needle:
        return list(range(start, len(lines) + 1))
    width = len(needle)
    return [
        pos
        for pos in range(start, len(lines) - width + 1)
        if tuple(lines[pos : pos + width]) == needle
    ]


def _nearest_line(lines: list[str], expected: tuple[str, ...]) -> int | None:
    anchors = [line for line in expected if line]
    if not anchors:
        return 1
    for anchor in anchors:
        for index, actual in enumerate(lines):
            if anchor in actual or actual in anchor:
                return index + 1
    return None


def apply_hunks(
    text: str,
    hunks: tuple[PatchHunk, ...],
    *,
    file: str,
) -> tuple[str, tuple[PatchConflict, ...]]:
    lines = text.split("\n") if text else []
    conflicts: list[PatchConflict] = []
    for hunk_number, hunk in enumerate(hunks, start=1):
        old = hunk.old_lines
        # Match against the current in-memory snapshot. Searching the full
        # document permits adjacent hunks to share context lines; changes from
        # earlier hunks are already reflected, so stale context still fails.
        candidates = _candidate_positions(lines, old, 0)
        if len(candidates) > 1 and hunk.hint:
            hinted = [
                position
                for position in candidates
                if any(
                    hunk.hint in line
                    for line in lines[position : position + max(1, len(old))]
                )
            ]
            if hinted:
                candidates = hinted
        if len(candidates) != 1:
            code = "ambiguous_context" if len(candidates) > 1 else "context_mismatch"
            message = (
                f"Hunk {hunk_number} for {file!r} matches {len(candidates)} locations"
                if candidates
                else f"Hunk {hunk_number} context was not found in {file!r}"
            )
            conflicts.append(
                PatchConflict(
                    code,
                    message,
                    file=file,
                    hunk=hunk_number,
                    expected=old[:12],
                    nearest_line=_nearest_line(lines, old),
                ),
            )
            continue
        position = candidates[0]
        replacement = list(hunk.new_lines)
        lines[position : position + len(old)] = replacement
    return "\n".join(lines), tuple(conflicts)

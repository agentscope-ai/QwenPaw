# -*- coding: utf-8 -*-
"""Filesystem validation and immutable planning for patch transactions."""

from __future__ import annotations

from pathlib import Path

from ..services.workspace_files import resolve_workspace_path
from .encoding import decode_snapshot, encode_text
from .errors import PatchError
from .matcher import apply_hunks
from .models import (
    FileOperationKind,
    PatchConflict,
    PatchDocument,
    PatchPlan,
    PlannedMutation,
)

_MAX_FILE_BYTES = 200 * 1024 * 1024


def resolve_patch_paths(root: Path, document: PatchDocument) -> dict[str, Path]:
    try:
        return {
            raw: resolve_workspace_path(root, raw, portable=True)
            for raw in document.target_paths()
        }
    except ValueError as exc:
        raise PatchError("unsafe_path", f"Unsafe patch path: {exc}") from exc


def build_plan(
    root: Path,
    document: PatchDocument,
    resolved: dict[str, Path],
) -> PatchPlan:
    mutations: dict[Path, PlannedMutation] = {}
    conflicts: list[PatchConflict] = []
    files: list[str] = []
    hunk_count = 0

    for operation in document.operations:
        source = resolved[operation.path]
        destination = resolved[operation.new_path] if operation.new_path else source
        files.extend(
            [operation.path] + ([operation.new_path] if operation.new_path else [])
        )
        involved = {source, destination}
        if any(path in mutations for path in involved):
            conflicts.append(
                PatchConflict(
                    "duplicate_operation",
                    f"Patch contains overlapping operations for {operation.path!r}",
                    file=operation.path,
                ),
            )
            continue

        if operation.kind is FileOperationKind.ADD:
            if source.exists():
                conflicts.append(
                    PatchConflict(
                        "target_exists",
                        f"Add target {operation.path!r} already exists",
                        file=operation.path,
                    ),
                )
                continue
            text = "\n".join(operation.add_lines)
            content = encode_text(
                text,
                newline="\n",
                trailing_newline=bool(operation.add_lines),
                bom=False,
            )
            mutations[source] = PlannedMutation(source, content)
            continue

        if not source.exists():
            conflicts.append(
                PatchConflict(
                    "source_missing",
                    f"Source {operation.path!r} does not exist",
                    file=operation.path,
                ),
            )
            continue
        if not source.is_file():
            conflicts.append(
                PatchConflict(
                    "not_a_file",
                    f"Source {operation.path!r} is not a regular file",
                    file=operation.path,
                ),
            )
            continue
        if source.stat().st_size > _MAX_FILE_BYTES:
            conflicts.append(
                PatchConflict(
                    "file_too_large",
                    f"Source {operation.path!r} exceeds the 200 MiB limit",
                    file=operation.path,
                ),
            )
            continue

        if operation.kind is FileOperationKind.DELETE:
            mutations[source] = PlannedMutation(source, None)
            continue

        if destination != source and destination.exists():
            conflicts.append(
                PatchConflict(
                    "move_target_exists",
                    f"Move target {operation.new_path!r} already exists",
                    file=operation.new_path,
                ),
            )
            continue
        snapshot = decode_snapshot(source, source.read_bytes())
        updated, hunk_conflicts = apply_hunks(
            snapshot.text,
            operation.hunks,
            file=operation.path,
        )
        if hunk_conflicts:
            conflicts.extend(hunk_conflicts)
            continue
        content = encode_text(
            updated,
            newline=snapshot.newline,
            trailing_newline=snapshot.trailing_newline,
            bom=snapshot.bom,
        )
        hunk_count += len(operation.hunks)
        if destination != source:
            mutations[source] = PlannedMutation(source, None, snapshot.mode)
        mutations[destination] = PlannedMutation(destination, content, snapshot.mode)

    if conflicts:
        raise PatchError(
            "patch_conflict",
            f"Patch validation failed with {len(conflicts)} conflict(s)",
            conflicts=tuple(conflicts),
        )
    return PatchPlan(
        tuple(mutations[path] for path in sorted(mutations, key=lambda p: str(p))),
        tuple(dict.fromkeys(path for path in files if path)),
        hunk_count,
    )

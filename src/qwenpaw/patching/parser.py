# -*- coding: utf-8 -*-
"""Strict parser for the model-friendly ``*** Begin Patch`` DSL."""

from __future__ import annotations

from .errors import PatchError
from .models import (
    FileOperation,
    FileOperationKind,
    HunkLine,
    PatchDocument,
    PatchHunk,
)

_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_ADD = "*** Add File: "
_DELETE = "*** Delete File: "
_UPDATE = "*** Update File: "
_MOVE = "*** Move to: "
_MAX_OPERATIONS = 100


def _parse_hunks(lines: list[str], path: str) -> tuple[PatchHunk, ...]:
    hunks: list[PatchHunk] = []
    hint = ""
    current: list[HunkLine] = []

    def finish() -> None:
        nonlocal current
        if not current:
            return
        if not any(line.kind in {"+", "-"} for line in current):
            raise PatchError(
                "invalid_hunk",
                f"Update hunk for {path!r} contains no changes",
            )
        hunks.append(PatchHunk(tuple(current), hint=hint))
        current = []

    for raw in lines:
        if raw.startswith("@@"):
            finish()
            hint = raw[2:].strip()
            continue
        if not raw or raw[0] not in {" ", "+", "-"}:
            raise PatchError(
                "invalid_hunk_line",
                f"Every update line for {path!r} must start with "
                "space, +, or -",
            )
        current.append(HunkLine(raw[0], raw[1:]))
    finish()
    if not hunks:
        raise PatchError("missing_hunk", f"Update for {path!r} has no hunks")
    return tuple(hunks)


def parse_patch(  # pylint: disable=too-many-branches,too-many-statements
    source: str,
) -> PatchDocument:
    """Parse one complete patch without touching the filesystem."""
    if not isinstance(source, str):
        raise PatchError("invalid_patch", "Patch must be a string")
    lines = source.splitlines()
    if not lines or lines[0] != _BEGIN:
        raise PatchError("missing_begin", f"Patch must start with {_BEGIN!r}")
    if lines[-1] != _END:
        raise PatchError("missing_end", f"Patch must end with {_END!r}")

    operations: list[FileOperation] = []
    index = 1
    while index < len(lines) - 1:
        header = lines[index]
        index += 1
        if header.startswith(_ADD):
            kind = FileOperationKind.ADD
            path = header[len(_ADD) :]
        elif header.startswith(_DELETE):
            kind = FileOperationKind.DELETE
            path = header[len(_DELETE) :]
        elif header.startswith(_UPDATE):
            kind = FileOperationKind.UPDATE
            path = header[len(_UPDATE) :]
        else:
            raise PatchError(
                "unknown_header",
                f"Unknown patch header: {header!r}",
            )
        if not path:
            raise PatchError("empty_path", "Patch file path cannot be empty")

        new_path: str | None = None
        if kind is FileOperationKind.UPDATE and index < len(lines) - 1:
            if lines[index].startswith(_MOVE):
                new_path = lines[index][len(_MOVE) :]
                index += 1
                if not new_path:
                    raise PatchError(
                        "empty_move_path",
                        "Move destination is empty",
                    )

        body: list[str] = []
        while index < len(lines) - 1 and not lines[index].startswith("*** "):
            body.append(lines[index])
            index += 1

        if kind is FileOperationKind.UPDATE and index < len(lines) - 1:
            if lines[index].startswith(_MOVE):
                if new_path is not None:
                    raise PatchError(
                        "duplicate_move",
                        f"Update for {path!r} has more than one "
                        "move destination",
                    )
                new_path = lines[index][len(_MOVE) :]
                index += 1
                if not new_path:
                    raise PatchError(
                        "empty_move_path",
                        "Move destination is empty",
                    )

        if kind is FileOperationKind.ADD:
            if any(not line.startswith("+") for line in body):
                raise PatchError(
                    "invalid_add_line",
                    f"Every added-file line for {path!r} must start with +",
                )
            operations.append(
                FileOperation(
                    kind,
                    path,
                    add_lines=tuple(line[1:] for line in body),
                ),
            )
        elif kind is FileOperationKind.DELETE:
            if body:
                raise PatchError(
                    "delete_has_body",
                    f"Delete operation for {path!r} must not contain hunks",
                )
            operations.append(FileOperation(kind, path))
        else:
            operations.append(
                FileOperation(
                    kind,
                    path,
                    hunks=_parse_hunks(body, path),
                    new_path=new_path,
                ),
            )
        if len(operations) > _MAX_OPERATIONS:
            raise PatchError(
                "too_many_files",
                f"Patch exceeds the {_MAX_OPERATIONS}-operation limit",
            )

    if not operations:
        raise PatchError("empty_patch", "Patch contains no file operations")
    return PatchDocument(tuple(operations))

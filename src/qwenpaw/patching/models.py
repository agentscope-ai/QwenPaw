# -*- coding: utf-8 -*-
"""Immutable models shared by the patch parser, planner and executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class FileOperationKind(str, Enum):
    ADD = "add"
    DELETE = "delete"
    UPDATE = "update"


@dataclass(frozen=True)
class HunkLine:
    kind: str
    text: str


@dataclass(frozen=True)
class PatchHunk:
    lines: tuple[HunkLine, ...]
    hint: str = ""

    @property
    def old_lines(self) -> tuple[str, ...]:
        return tuple(line.text for line in self.lines if line.kind != "+")

    @property
    def new_lines(self) -> tuple[str, ...]:
        return tuple(line.text for line in self.lines if line.kind != "-")


@dataclass(frozen=True)
class FileOperation:
    kind: FileOperationKind
    path: str
    hunks: tuple[PatchHunk, ...] = ()
    new_path: str | None = None
    add_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatchDocument:
    operations: tuple[FileOperation, ...]

    def target_paths(self) -> tuple[str, ...]:
        paths: list[str] = []
        for operation in self.operations:
            paths.append(operation.path)
            if operation.new_path:
                paths.append(operation.new_path)
        return tuple(dict.fromkeys(paths))


@dataclass(frozen=True)
class TextSnapshot:
    path: Path
    raw: bytes
    text: str
    newline: str
    trailing_newline: bool
    bom: bool
    mode: int


@dataclass(frozen=True)
class PlannedMutation:
    path: Path
    content: bytes | None
    mode: int = 0o644


@dataclass(frozen=True)
class PatchPlan:
    mutations: tuple[PlannedMutation, ...]
    files: tuple[str, ...]
    hunks_applied: int


@dataclass(frozen=True)
class PatchConflict:
    code: str
    message: str
    file: str | None = None
    hunk: int | None = None
    expected: tuple[str, ...] = ()
    nearest_line: int | None = None
    phase: str = "validation"

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "file": self.file,
            "hunk": self.hunk,
            "expected": list(self.expected),
            "nearest_line": self.nearest_line,
            "phase": self.phase,
        }


@dataclass(frozen=True)
class PatchResult:
    status: str
    files: tuple[str, ...] = ()
    hunks_applied: int = 0
    conflicts: tuple[PatchConflict, ...] = ()
    rolled_back: bool = False
    rollback_errors: tuple[str, ...] = field(default_factory=tuple)

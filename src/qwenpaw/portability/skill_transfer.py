# -*- coding: utf-8 -*-
"""Shared, bounded traversal for imported Skill trees."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

MAX_SKILL_FILES = 5_000
MAX_SKILL_ENTRIES = 6_000
MAX_SKILL_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class SkillTreeEntry:
    relative: Path
    mode: int
    data: bytes | None = None

    @property
    def is_dir(self) -> bool:
        return self.data is None


def write_tree_entry(root: Path, entry: SkillTreeEntry) -> None:
    """Write one bounded snapshot entry under a private target root."""
    output = root / entry.relative
    if entry.is_dir:
        output.mkdir(parents=True, mode=0o700, exist_ok=True)
        return
    output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    output.write_bytes(entry.data or b"")
    os.chmod(output, 0o700 if entry.mode & stat.S_IXUSR else 0o600)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def read_regular_file(
    path: Path,
    *,
    expected: os.stat_result | None = None,
    max_bytes: int | None = None,
) -> bytes:
    """Read one stable bounded regular file without following links."""
    before = expected or path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError("portable source is not a regular file")
    if max_bytes is not None and before.st_size > max_bytes:
        raise ValueError("portable source exceeds the byte safety limit")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(
            before,
        ):
            raise ValueError("portable source changed during import")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            data = stream.read(opened.st_size + 1)
            after = os.fstat(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(data) != opened.st_size or _identity(after) != _identity(opened):
        raise ValueError("portable source changed during import")
    return data


def read_bounded_tree(  # pylint: disable=too-many-branches
    source: Path,
    *,
    required_file: str = "",
    excluded_dirs: frozenset[str] = frozenset(),
    reject_unsafe: bool = True,
    read_data: bool = True,
) -> Iterator[SkillTreeEntry]:
    """Yield one link-free tree with stable, bounded file snapshots."""
    source = source.expanduser()
    if source.is_symlink():
        raise ValueError("portable source is a symbolic link")
    root = source.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("portable source is not a directory")
    if required_file and not (root / required_file).is_file():
        raise ValueError(f"portable source has no {required_file}")

    entries = files = total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        if directory.is_symlink() or not directory.resolve().is_relative_to(
            root,
        ):
            raise ValueError("portable directory escapes its source root")
        with os.scandir(directory) as iterator:
            for item in iterator:
                entries += 1
                if entries > MAX_SKILL_ENTRIES:
                    raise ValueError("source exceeds the entry safety limit")
                path = Path(item.path)
                if item.is_symlink():
                    if reject_unsafe:
                        raise ValueError("source contains a symbolic link")
                    continue
                if not path.resolve(strict=True).is_relative_to(root):
                    raise ValueError("source entry escapes its root")
                relative = path.relative_to(root)
                if item.is_dir(follow_symlinks=False):
                    if item.name not in excluded_dirs:
                        pending.append(path)
                        yield SkillTreeEntry(relative, 0o700)
                    continue
                if not item.is_file(follow_symlinks=False):
                    if reject_unsafe:
                        raise ValueError("source contains a non-regular entry")
                    continue

                before = item.stat(follow_symlinks=False)
                files += 1
                total += before.st_size
                if files > MAX_SKILL_FILES or total > MAX_SKILL_BYTES:
                    raise ValueError("source exceeds file or byte limits")
                yield SkillTreeEntry(
                    relative,
                    before.st_mode,
                    (
                        read_regular_file(path, expected=before)
                        if read_data
                        else b""
                    ),
                )


def read_bounded_skill_tree(source: Path) -> Iterator[SkillTreeEntry]:
    """Yield one link-free Skill tree with stable, bounded snapshots."""
    yield from read_bounded_tree(source, required_file="SKILL.md")


def copy_bounded_tree(
    source: Path,
    target: Path,
    *,
    required_file: str = "",
) -> None:
    """Copy one bounded source tree into a new private directory."""
    target.mkdir(mode=0o700)
    for entry in read_bounded_tree(source, required_file=required_file):
        write_tree_entry(target, entry)

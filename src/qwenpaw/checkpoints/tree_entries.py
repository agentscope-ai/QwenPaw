# -*- coding: utf-8 -*-
"""Git tree entry metadata used by checkpoint restore."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CheckpointError

REGULAR_TREE_MODES = {"100644": 0o644, "100755": 0o755}
SYMLINK_TREE_MODE = "120000"
_RESTORABLE_TREE_MODES = frozenset(
    {*REGULAR_TREE_MODES, SYMLINK_TREE_MODE},
)


@dataclass(frozen=True)
class TreeEntry:
    """One restorable Git tree entry without eagerly loaded content."""

    mode: str
    object_id: str


def parse_tree_entries(
    output: str,
    *,
    commit: str,
    paths: set[str] | None = None,
) -> dict[str, TreeEntry]:
    """Parse NUL-delimited ``git ls-tree`` output."""
    entries: dict[str, TreeEntry] = {}
    for item in output.split("\0"):
        if not item:
            continue
        header, separator, path = item.partition("\t")
        fields = header.split()
        if not separator or not path or len(fields) != 3:
            raise CheckpointError(
                "Checkpoint contains malformed Git tree entry "
                f"in {commit[:12]}",
            )
        if paths is not None and path not in paths:
            continue
        mode, object_type, object_id = fields
        if object_type != "blob" or mode not in _RESTORABLE_TREE_MODES:
            raise CheckpointError(
                "Checkpoint contains unsupported Git tree entry "
                f"{path}: mode={mode}, type={object_type}",
            )
        entries[path] = TreeEntry(mode=mode, object_id=object_id)
    return entries


__all__ = [
    "REGULAR_TREE_MODES",
    "SYMLINK_TREE_MODE",
    "TreeEntry",
    "parse_tree_entries",
]

#!/usr/bin/env python3
"""Merge a newly built plugin index with a historical one from OSS.

Used by the ``plugins-release.yml`` workflow to preserve old plugin
versions on the CDN while adding new ones.

Merge rules:
- ``files``: keyed by file_id (``{plugin_id}-{version}``).  New entries
  overwrite same-id old entries; different ids from old are preserved.
- ``platforms.{kind}.versions``: union of new and old version lists,
  new versions first, old versions appended with deduplication.

Usage::

    python scripts/pack/merge_plugin_index.py \
        --new  dist/plugins/index.json \
        --old  existing-index.json \
        --out  dist/plugins/index.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def merge_indexes(new_index: dict, old_index: dict) -> dict:
    """Merge *old_index* into *new_index* (mutates and returns *new_index*)."""
    # files: same file_id is overwritten by new; different ids preserved.
    old_files = old_index.get("files", {})
    new_files = new_index.get("files", {})
    new_index["files"] = {**old_files, **new_files}

    # platforms.versions: union, new first, old appended with dedup.
    old_platforms = old_index.get("platforms", {})
    all_kinds = set(
        list(new_index.get("platforms", {}).keys())
        + list(old_platforms.keys()),
    )
    for kind in all_kinds:
        old_versions = old_platforms.get(kind, {}).get("versions", [])
        new_versions = (
            new_index.get("platforms", {}).get(kind, {}).get("versions", [])
        )
        seen = set(new_versions)
        merged = list(new_versions)
        for v in old_versions:
            if v not in seen:
                merged.append(v)
                seen.add(v)
        new_index.setdefault("platforms", {})
        new_index["platforms"].setdefault(kind, {})
        new_index["platforms"][kind]["versions"] = merged

    return new_index


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Merge new and historical plugin indexes.",
    )
    parser.add_argument(
        "--new",
        required=True,
        type=Path,
        help="Path to the newly generated index.json",
    )
    parser.add_argument(
        "--old",
        required=True,
        type=Path,
        help="Path to the existing (historical) index.json",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output path for the merged index.json",
    )
    args = parser.parse_args(argv)

    with open(args.new, encoding="utf-8") as f:
        new_index = json.load(f)
    with open(args.old, encoding="utf-8") as f:
        old_index = json.load(f)

    merged = merge_indexes(new_index, old_index)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()

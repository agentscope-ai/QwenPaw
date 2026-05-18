#!/usr/bin/env python3
"""Scan local plugins, build distributable zips, and emit OSS metadata.

Mirrors the shape of ``generate_oss_metadata.py`` so the resulting
``metadata/plugins/index.json`` is a drop-in product entry for the existing
Downloads page (it iterates ``mainIndex.products`` regardless of product type).

Layout produced under ``--dist``::

    dist/plugins/
        bundle/<id>-<version>-<sha8>.zip
        tool/<id>-<version>-<sha8>.zip
        index.json

Each plugin source tree is full-rebuild zipped: this means deletions in the
repo propagate through to OSS on the next run (no stale entries left behind).
The ``-<sha8>`` content-hash suffix means a code change without a version bump
still produces a new immutable URL, so the install command always points at
fresh content.

A plugin can opt out of publishing by setting ``"publish": false`` in its
``plugin.json``.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KIND_DIRS = ("bundle", "tool")

EXCLUDE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    ".git",
    ".gitignore",
    "node_modules",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "*.log",
)


def _is_excluded(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_PATTERNS)


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of_tree(plugin_dir: Path) -> str:
    """Hash the (sorted, filtered) source tree so the result is deterministic
    regardless of FS ordering or zip metadata. Used for the URL suffix."""
    h = hashlib.sha256()
    for rel in _iter_tree_relpaths(plugin_dir):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update((plugin_dir / rel).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _iter_tree_relpaths(plugin_dir: Path) -> list[str]:
    rels: list[str] = []
    for root, dirs, files in os.walk(plugin_dir):
        dirs[:] = [d for d in dirs if not _is_excluded(d)]
        for fname in files:
            if _is_excluded(fname):
                continue
            rels.append(str((Path(root) / fname).relative_to(plugin_dir)))
    rels.sort()
    return rels


def _zip_plugin(plugin_dir: Path, out_zip: Path) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in _iter_tree_relpaths(plugin_dir):
            zf.write(plugin_dir / rel, f"{plugin_dir.name}/{rel}")


def _read_manifest(plugin_dir: Path) -> dict[str, Any] | None:
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.is_file():
        return None
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"WARNING: skipping {plugin_dir} - cannot read plugin.json: {exc}",
            file=sys.stderr,
        )
        return None


def _localized(text: str) -> dict[str, str]:
    return {"zh-CN": text, "en-US": text}


def _build_metadata(
    manifest: dict[str, Any],
    *,
    file_id: str,
    plugin_id: str,
    version: str,
    kind: str,
    zip_path: Path,
    cdn_path: str,
) -> dict[str, Any]:
    size_bytes = zip_path.stat().st_size
    name = str(manifest.get("name") or plugin_id)
    description = str(manifest.get("description") or "")

    return {
        "id": file_id,
        "plugin_id": plugin_id,
        "name": _localized(name),
        "description": _localized(description),
        "product": "plugins",
        "platform": kind,
        "version": version,
        "author": str(manifest.get("author") or ""),
        "filename": zip_path.name,
        "url": cdn_path,
        "size": _format_size(size_bytes),
        "size_bytes": size_bytes,
        "sha256": _sha256_of_file(zip_path),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "type": "zip",
    }


def discover_and_pack(
    plugins_root: Path,
    dist_root: Path,
    cdn_prefix: str,
) -> dict[str, Any]:
    """Scan, zip, and assemble the plugins index. Always full-rebuild."""
    index: dict[str, Any] = {
        "product": "plugins",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "platforms": {},
        "files": {},
    }

    if not plugins_root.is_dir():
        print(
            f"WARNING: plugins root does not exist: {plugins_root}",
            file=sys.stderr,
        )
        return index

    for kind in KIND_DIRS:
        kind_dir = plugins_root / kind
        if not kind_dir.is_dir():
            continue
        for plugin_dir in sorted(p for p in kind_dir.iterdir() if p.is_dir()):
            manifest = _read_manifest(plugin_dir)
            if manifest is None:
                continue
            if manifest.get("publish") is False:
                print(f"  - skip {plugin_dir.name} (publish=false)")
                continue

            plugin_id = str(manifest.get("id") or plugin_dir.name)
            version = str(manifest.get("version") or "0.0.0")
            content_sha = _sha256_of_tree(plugin_dir)[:8]
            zip_name = f"{plugin_id}-{version}-{content_sha}.zip"
            zip_path = dist_root / kind / zip_name

            print(f"  + pack {kind}/{plugin_dir.name} -> {zip_path.name}")
            _zip_plugin(plugin_dir, zip_path)

            cdn_path = f"{cdn_prefix.rstrip('/')}/{kind}/{zip_name}"
            file_id = f"{plugin_id}-{version}-{content_sha}"
            metadata = _build_metadata(
                manifest,
                file_id=file_id,
                plugin_id=plugin_id,
                version=version,
                kind=kind,
                zip_path=zip_path,
                cdn_path=cdn_path,
            )
            index["files"][file_id] = metadata
            kind_entry = index["platforms"].setdefault(kind, {"versions": []})
            if file_id not in kind_entry["versions"]:
                kind_entry["versions"].insert(0, file_id)

    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugins-root",
        default="plugins",
        help="Path to the plugins/ directory (default: plugins)",
    )
    parser.add_argument(
        "--dist",
        default="dist/plugins",
        help="Output directory for zip artifacts (default: dist/plugins)",
    )
    parser.add_argument(
        "--metadata-out",
        default=None,
        help=(
            "Where to write the assembled plugins index JSON. "
            "Defaults to <dist>/index.json."
        ),
    )
    parser.add_argument(
        "--cdn-prefix",
        default="/files/plugins",
        help="OSS path prefix used in metadata URLs (default: /files/plugins)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan + plan only; do not write zips or index.",
    )
    args = parser.parse_args()

    plugins_root = Path(args.plugins_root).resolve()
    dist_root = Path(args.dist).resolve()
    metadata_out = Path(
        args.metadata_out
        if args.metadata_out is not None
        else dist_root / "index.json"
    ).resolve()

    print(f"Scanning plugins under: {plugins_root}")
    if args.dry_run:
        # Dry-run: list what would be packed without writing anything.
        for kind in KIND_DIRS:
            kind_dir = plugins_root / kind
            if not kind_dir.is_dir():
                continue
            for plugin_dir in sorted(
                p for p in kind_dir.iterdir() if p.is_dir()
            ):
                manifest = _read_manifest(plugin_dir)
                if manifest is None:
                    continue
                if manifest.get("publish") is False:
                    print(f"  - skip {plugin_dir.name} (publish=false)")
                    continue
                print(
                    f"  ~ would pack {kind}/{plugin_dir.name} "
                    f"(id={manifest.get('id')}, "
                    f"version={manifest.get('version')})"
                )
        print("Dry run complete.")
        return 0

    if dist_root.exists():
        # Wipe stale zips so deletions / sha changes propagate cleanly.
        for kind in KIND_DIRS:
            kind_root = dist_root / kind
            if kind_root.is_dir():
                for child in kind_root.iterdir():
                    if child.is_file():
                        child.unlink()
    dist_root.mkdir(parents=True, exist_ok=True)

    index = discover_and_pack(plugins_root, dist_root, args.cdn_prefix)

    metadata_out.parent.mkdir(parents=True, exist_ok=True)
    with metadata_out.open("w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print()
    print(f"Wrote index: {metadata_out}")
    n_files = len(index["files"])
    n_kinds = len(index["platforms"])
    print(f"  {n_files} plugin(s) across {n_kinds} kind(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

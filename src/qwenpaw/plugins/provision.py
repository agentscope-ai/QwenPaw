# -*- coding: utf-8 -*-
"""On-disk provision inventory and ``provision_files``."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from ..utils.io_utils import write_json_atomic

logger = logging.getLogger(__name__)


def provisions_dir() -> Path:
    """Return the inventory directory (created on demand)."""
    from ..constant import WORKING_DIR

    path = Path(WORKING_DIR) / "plugin_provisions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def inventory_path(plugin_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in plugin_id)
    return provisions_dir() / f"{safe}.json"


def load_inventory(plugin_id: str) -> dict[str, Any]:
    path = inventory_path(plugin_id)
    if not path.is_file():
        return {
            "plugin_id": plugin_id,
            "locations": {},
            "tools": {},
            "provisions": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Corrupt provision inventory for '%s'", plugin_id)
        return {
            "plugin_id": plugin_id,
            "locations": {},
            "tools": {},
            "provisions": [],
        }
    data.setdefault("plugin_id", plugin_id)
    data.setdefault("locations", {})
    data.setdefault("tools", {})
    data.setdefault("provisions", [])
    return data


def save_inventory(plugin_id: str, data: dict[str, Any]) -> None:
    write_json_atomic(inventory_path(plugin_id), data)


def delete_inventory(plugin_id: str) -> None:
    path = inventory_path(plugin_id)
    if path.is_file():
        path.unlink()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 64), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_tool_factory(
    plugin_id: str,
    tool_name: str,
    factory: dict[str, Any],
) -> None:
    """Persist the out-of-box BuiltinToolConfig snapshot for *tool_name*."""
    data = load_inventory(plugin_id)
    data["tools"][tool_name] = {"factory": dict(factory)}
    save_inventory(plugin_id, data)


def record_escape_provision(plugin_id: str, desc: str) -> None:
    data = load_inventory(plugin_id)
    rows = data["provisions"]
    if not any(row.get("desc") == desc for row in rows):
        rows.append({"desc": desc, "kind": "escape"})
    save_inventory(plugin_id, data)


def _iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return [p for p in root.rglob("*") if p.is_file()]


def _rel(root: Path, path: Path) -> str:
    if root.is_file():
        return path.name
    return str(path.relative_to(root)).replace("\\", "/")


def provision_files(
    plugin_id: str,
    src: Path,
    dest: Path,
    version: str,
) -> str:
    """Copy factory files with three-way merge. Returns the applied branch.

    Branches: ``create`` (new), ``keep`` (leave user files), ``migrate``.
    """
    src = Path(src)
    dest = Path(dest)
    if not src.exists():
        raise FileNotFoundError(f"provision src not found: {src}")

    dest_key = str(dest)
    data = load_inventory(plugin_id)
    locations: dict[str, Any] = data["locations"]
    previous = locations.get(dest_key) or {}
    prev_version = previous.get("version")
    prev_files: dict[str, Any] = previous.get("files") or {}

    if dest.exists() and prev_version == version:
        return "keep"

    if dest.exists() and not prev_version:
        # Inventory missing: treat as user-owned, do not overwrite.
        locations[dest_key] = {
            "src": str(src),
            "version": version,
            "branch": "keep",
            "files": prev_files,
            "migrating": None,
        }
        save_inventory(plugin_id, data)
        return "keep"

    branch = "create" if not dest.exists() else "migrate"
    backup = None
    if branch == "migrate":
        backup = _begin_migration(
            plugin_id,
            src,
            dest,
            dest_key,
            version,
            prev_version,
            prev_files,
            data,
        )
    new_files = _apply_factory_copy(src, dest, prev_files, branch)
    marker = None
    if branch == "migrate" and backup is not None:
        marker = {
            "backup_path": str(backup),
            "target_version": version,
            "prev_version": prev_version,
            "prev_factory_hashes": {
                rel: (info or {}).get("factory_hash", "")
                for rel, info in prev_files.items()
            },
        }
    locations[dest_key] = {
        "src": str(src),
        "version": version,
        "branch": branch,
        "files": new_files,
        "migrating": marker,
    }
    save_inventory(plugin_id, data)
    return branch


def _begin_migration(
    plugin_id: str,
    src: Path,
    dest: Path,
    dest_key: str,
    version: str,
    prev_version: Any,
    prev_files: dict[str, Any],
    data: dict[str, Any],
) -> Path:
    backup = dest.with_name(dest.name + f".{plugin_id}.bak")
    _remove_path(backup)
    if dest.is_dir():
        shutil.copytree(dest, backup)
    else:
        shutil.copy2(dest, backup)
    data["locations"][dest_key] = {
        "src": str(src),
        "version": prev_version,
        "branch": "migrate",
        "files": prev_files,
        "migrating": {
            "backup_path": str(backup),
            "target_version": version,
            "prev_version": prev_version,
            "prev_factory_hashes": {
                rel: (info or {}).get("factory_hash", "")
                for rel, info in prev_files.items()
            },
        },
    }
    save_inventory(plugin_id, data)
    return backup


def _apply_factory_copy(
    src: Path,
    dest: Path,
    prev_files: dict[str, Any],
    branch: str,
) -> dict[str, Any]:
    new_files: dict[str, Any] = {}
    if src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _copy_one(src, dest, prev_files.get(src.name), branch)
        new_files[src.name] = {"factory_hash": file_sha256(src)}
        return new_files
    dest.mkdir(parents=True, exist_ok=True)
    src_rels: set[str] = set()
    for path in _iter_files(src):
        rel = _rel(src, path)
        src_rels.add(rel)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_one(path, target, prev_files.get(rel), branch)
        new_files[rel] = {"factory_hash": file_sha256(path)}
    if branch != "migrate":
        return new_files
    for rel, info in prev_files.items():
        if rel in src_rels:
            continue
        target = dest / rel
        if not target.is_file():
            continue
        old_hash = (info or {}).get("factory_hash", "")
        if old_hash and file_sha256(target) == old_hash:
            target.unlink()
    return new_files


def _remove_path(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def _copy_one(
    src_file: Path,
    dest_file: Path,
    prev_info: dict[str, Any] | None,
    branch: str,
) -> None:
    if branch == "create" or not dest_file.exists():
        shutil.copy2(src_file, dest_file)
        return
    old_hash = (prev_info or {}).get("factory_hash", "")
    if old_hash and dest_file.is_file() and file_sha256(dest_file) == old_hash:
        shutil.copy2(src_file, dest_file)
        return
    if dest_file.is_file() and file_sha256(dest_file) == file_sha256(src_file):
        return
    # User edited this file: keep it, drop a .new sibling when factory moved.
    if dest_file.is_file() and file_sha256(src_file) != file_sha256(dest_file):
        sibling = dest_file.with_name(dest_file.name + ".new")
        shutil.copy2(src_file, sibling)


def recover_migrating_inventory(
    plugin_id: str | None = None,
    *,
    owns_commit=None,
) -> list[str]:
    """Restore any location still marked migrating. Returns plugin ids."""
    recovered: list[str] = []
    if plugin_id is not None:
        ids = [plugin_id]
    else:
        from ..constant import WORKING_DIR

        if not Path(WORKING_DIR).joinpath("plugin_provisions").is_dir():
            return recovered
        ids = [p.stem for p in provisions_dir().glob("*.json")]
    for item_id in ids:
        if owns_commit is not None and not owns_commit(item_id):
            continue
        data = load_inventory(item_id)
        changed = False
        for dest_key, loc in list((data.get("locations") or {}).items()):
            marker = (loc or {}).get("migrating")
            if not marker:
                continue
            backup = Path(marker.get("backup_path") or "")
            dest = Path(dest_key)
            _restore_backup(backup, dest)
            loc["version"] = marker.get("prev_version")
            loc["migrating"] = None
            hashes = marker.get("prev_factory_hashes") or {}
            loc["files"] = {
                rel: {"factory_hash": digest} for rel, digest in hashes.items()
            }
            changed = True
        if changed:
            save_inventory(item_id, data)
            recovered.append(item_id)
            logger.warning(
                "Restored in-progress provision migration for plugin '%s'",
                item_id,
            )
    return recovered


def _restore_backup(backup: Path, dest: Path) -> None:
    """Replace *dest* with *backup* if the backup still exists."""
    if not backup.exists():
        return
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    if backup.is_dir():
        shutil.copytree(backup, dest)
        shutil.rmtree(backup)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, dest)
    backup.unlink()


_PLUGIN_OWNED_TOOL_FIELDS = (
    "description",
    "icon",
    "display_to_user",
)
_USER_OWNED_TOOL_FIELDS = (
    "enabled",
    "async_execution",
    "config",
)


def apply_tool_factory(
    plugin_id: str,
    tool_name: str,
    factory: dict[str, Any],
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge one BuiltinToolConfig by field ownership.

    Plugin-owned fields follow the new factory when the user did not
    edit them. User-owned fields are always kept.
    """
    data = load_inventory(plugin_id)
    tools: dict[str, Any] = data["tools"]
    previous = (tools.get(tool_name) or {}).get("factory") or {}
    merged = dict(factory)
    if current:
        for field_name in _PLUGIN_OWNED_TOOL_FIELDS:
            if field_name in current and field_name in previous:
                if current.get(field_name) != previous.get(field_name):
                    merged[field_name] = current[field_name]
            elif field_name in current and field_name not in previous:
                merged[field_name] = current[field_name]
        for field_name in _USER_OWNED_TOOL_FIELDS:
            if field_name in current:
                merged[field_name] = current[field_name]
    tools[tool_name] = {"factory": dict(factory)}
    save_inventory(plugin_id, data)
    return merged


def commit_migrations(plugin_id: str) -> None:
    """Clear migrating markers and delete their backups after a good load."""
    data = load_inventory(plugin_id)
    changed = False
    for loc in (data.get("locations") or {}).values():
        marker = (loc or {}).get("migrating")
        if not marker:
            continue
        backup = Path(marker.get("backup_path") or "")
        _remove_path(backup)
        loc["migrating"] = None
        changed = True
    if changed:
        save_inventory(plugin_id, data)


def snapshot_created_dests(plugin_id: str) -> list[str]:
    """Return dest keys this plugin created (uninstall recheck snapshot)."""
    data = load_inventory(plugin_id)
    dests: list[str] = []
    for dest_key, loc in (data.get("locations") or {}).items():
        if (loc or {}).get("branch") == "create":
            dests.append(dest_key)
    return dests


def leftover_dests(dests: list[str]) -> list[str]:
    """Return snapshot dests that are still on disk."""
    return [dest for dest in dests if Path(dest).exists()]


def declared_provision_dests(manifest: dict[str, Any]) -> list[str]:
    """Read dest paths declared on ``plugin.json`` (candidate fallback)."""
    raw = None
    meta = manifest.get("meta")
    if isinstance(meta, dict):
        raw = meta.get("provisions")
    if raw is None:
        raw = manifest.get("provisions")
    if not isinstance(raw, list):
        return []
    dests: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            dests.append(item.strip())
            continue
        if isinstance(item, dict):
            dest = item.get("dest") or item.get("destination")
            if isinstance(dest, str) and dest.strip():
                dests.append(dest.strip())
    return dests


def teardown_paths(dests: list[str]) -> None:
    """Best-effort delete of declared dests (candidate-level uninstall)."""
    for dest_key in dests:
        _remove_path(Path(dest_key))


def teardown_created_locations(plugin_id: str) -> None:
    """Remove destinations created by this plugin (uninstall only)."""
    data = load_inventory(plugin_id)
    for dest_key, loc in list((data.get("locations") or {}).items()):
        if (loc or {}).get("branch") != "create":
            continue
        dest = Path(dest_key)
        if not dest.exists():
            continue
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    delete_inventory(plugin_id)

# -*- coding: utf-8 -*-
"""On-disk provision inventory and ``provision_files``."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ..utils.io_utils import write_json_atomic
from .safe_fs import ensure_deletable, parse_optional_absolute, safe_remove

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


def recorded_tool_names(plugin_id: str) -> list[str]:
    """Tool names persisted for *plugin_id* when no instance is loaded."""
    data = load_inventory(plugin_id)
    return [name for name in (data.get("tools") or {}) if name]


def record_tool_factory(
    plugin_id: str,
    tool_name: str,
    factory: dict[str, Any],
) -> None:
    """Persist the out-of-box BuiltinToolConfig snapshot for *tool_name*."""
    data = load_inventory(plugin_id)
    data["tools"][tool_name] = {"factory": dict(factory)}
    save_inventory(plugin_id, data)


def record_escape_provision(
    plugin_id: str,
    desc: str,
    *,
    kind: str = "escape",
    teardown_ref: str | None = None,
) -> None:
    data = load_inventory(plugin_id)
    rows = data["provisions"]
    if not any(row.get("desc") == desc for row in rows):
        row: dict[str, Any] = {"desc": desc, "kind": kind or "escape"}
        if teardown_ref:
            row["teardown_ref"] = teardown_ref
        rows.append(row)
    save_inventory(plugin_id, data)


def drop_escape_provision(plugin_id: str, desc: str) -> None:
    """Remove one escape-provision inventory row after this-txn undo."""
    data = load_inventory(plugin_id)
    rows = list(data.get("provisions") or [])
    kept = [row for row in rows if row.get("desc") != desc]
    if len(kept) == len(rows):
        return
    data["provisions"] = kept
    save_inventory(plugin_id, data)


def undo_this_txn_escapes(
    plugin_id: str,
    escapes: list[tuple[str, Any]],
) -> None:
    """Undo this-txn escape rows and drop those inventory rows.

    ``teardown`` runs only when this transaction actually ran
    ``setup``. A ``None`` teardown only drops the newly written
    inventory row. Existing rows that did not run ``setup`` in this
    transaction are left alone.
    """
    for desc, teardown in reversed(list(escapes)):
        if teardown is not None:
            try:
                teardown()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "This-txn escape teardown %r failed for '%s'",
                    desc,
                    plugin_id,
                )
        drop_escape_provision(plugin_id, desc)


def replay_persisted_provisions(
    plugin_id: str,
    source_path: Path | None,
) -> None:
    """Rebuild official install-layer teardowns after the process restarts."""
    data = load_inventory(plugin_id)
    for row in data.get("provisions") or []:
        if not isinstance(row, dict):
            continue
        ref = str(row.get("teardown_ref") or "").strip()
        kind = str(row.get("kind") or "")
        if kind == "cloudpaw_agents" and not ref:
            ref = "agents_setup:uninstall_agents"
        if not ref:
            continue
        _call_teardown_ref(source_path, ref)


def _call_teardown_ref(source_path: Path | None, ref: str) -> None:
    module_name, _, func_name = ref.partition(":")
    if not module_name or not func_name:
        return
    module = None
    if source_path is not None:
        module_file = Path(source_path) / f"{module_name.replace('.', '/')}.py"
        if module_file.is_file():
            spec = importlib.util.spec_from_file_location(
                f"plugin_teardown_{module_file.stem}",
                module_file,
            )
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
    if module is None:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            logger.warning("Cannot import teardown %s", ref)
            return
    callback = getattr(module, func_name, None)
    if not callable(callback):
        logger.warning("Teardown %s is not callable", ref)
        return
    callback()


def _iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return [p for p in root.rglob("*") if p.is_file()]


def _rel(root: Path, path: Path) -> str:
    if root.is_file():
        return path.name
    return str(path.relative_to(root)).replace("\\", "/")


def location_owned(loc: dict[str, Any] | None) -> bool:
    """Whether the framework created this location and may delete it."""
    if not loc:
        return False
    if "owned" in loc:
        return bool(loc["owned"])
    # Read-only interpretation of the previous schema; never write ``branch``.
    return loc.get("branch") in {"create", "migrate"}


def provision_files(
    plugin_id: str,
    src: Path,
    dest: Path,
    version: str,
) -> str:
    """Copy factory files with three-way merge. Returns the applied branch.

    Branches live only in the return value: ``create``, ``keep``, ``migrate``.
    Durable inventory records ``owned``, never ``applied_branch``.
    """
    src = Path(src)
    dest = Path(dest)
    if not src.exists():
        raise FileNotFoundError(f"provision src not found: {src}")
    if not str(dest).strip() or dest in {Path(""), Path(".")}:
        raise ValueError("refusing to provision an empty dest")
    if not dest.is_absolute():
        dest = dest.resolve()

    dest_key = str(dest)
    data = load_inventory(plugin_id)
    locations: dict[str, Any] = data["locations"]
    previous = locations.get(dest_key) or {}
    prev_version = previous.get("version")
    prev_files: dict[str, Any] = previous.get("files") or {}
    owned = location_owned(previous)
    dest_existed = dest.exists()

    if dest_existed and prev_version == version:
        return "keep"

    if dest_existed and not prev_version:
        # User already had this path before the plugin created it.
        # Never use this branch for a half-finished create from this txn.
        locations[dest_key] = {
            "src": str(src),
            "version": version,
            "owned": False,
            "files": prev_files,
            "migrating": None,
        }
        save_inventory(plugin_id, data)
        return "keep"

    branch = "create" if not dest_existed else "migrate"
    if branch == "create":
        owned = True
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
            owned=owned,
        )
    try:
        if branch == "create":
            new_files = _create_via_staging(src, dest, prev_files)
        else:
            new_files = _apply_factory_copy(src, dest, prev_files, branch)
        marker = None
        if branch == "migrate" and backup is not None:
            marker = {
                "status": "prepared",
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
            "owned": owned,
            "files": new_files,
            "migrating": marker,
        }
        save_inventory(plugin_id, data)
    except Exception:
        if branch == "create" and not dest_existed and dest.exists():
            _remove_path(dest)
        raise
    return branch


def _allocate_provision_backup(dest: Path, plugin_id: str) -> Path:
    """Return a sibling backup path that does not already exist."""
    for _ in range(16):
        candidate = dest.with_name(
            f"{dest.name}.{plugin_id}.{uuid.uuid4().hex[:8]}.bak",
        )
        if not candidate.exists():
            return candidate
    raise RuntimeError(
        f"could not allocate a unique provision backup for '{plugin_id}'",
    )


def _begin_migration(
    plugin_id: str,
    src: Path,
    dest: Path,
    dest_key: str,
    version: str,
    prev_version: Any,
    prev_files: dict[str, Any],
    data: dict[str, Any],
    *,
    owned: bool,
) -> Path:
    previous = (data.get("locations") or {}).get(dest_key) or {}
    existing = parse_optional_absolute(
        (previous.get("migrating") or {}).get("backup_path"),
    )
    if existing is not None and existing.exists():
        return existing
    backup = _allocate_provision_backup(dest, plugin_id)
    if dest.is_dir():
        shutil.copytree(dest, backup)
    else:
        shutil.copy2(dest, backup)
    data["locations"][dest_key] = {
        "src": str(src),
        "version": prev_version,
        "owned": owned,
        "files": prev_files,
        "migrating": {
            "status": "prepared",
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


def _create_via_staging(
    src: Path,
    dest: Path,
    prev_files: dict[str, Any],
) -> dict[str, Any]:
    """Copy factory files on the same volume, then rename onto dest."""
    if dest.exists():
        raise RuntimeError(f"provision create dest already exists: {dest}")
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_absolute():
        raise ValueError("provision dest parent must be absolute")
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{dest.name or 'dest'}.prov-",
            dir=str(parent),
        ),
    )
    staging = staging_root / (dest.name or "dest")
    try:
        new_files = _apply_factory_copy(src, staging, prev_files, "create")
        if dest.exists():
            raise RuntimeError(
                f"provision dest appeared during create: {dest}",
            )
        os.rename(str(staging), str(dest))
        return new_files
    except Exception:
        if dest.exists():
            _remove_path(dest)
        raise
    finally:
        if staging_root.exists():
            safe_remove(
                staging_root,
                purpose="clear provision create staging",
            )


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
    if path is None:
        return
    raw = str(path).strip()
    if not raw:
        return
    safe_remove(path, purpose="remove provision path")


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


def commit_prepared_migrations(plugin_id: str) -> None:
    """Keep dests and drop backups for leftover migrating locations.

    Call only when the plugin directory update is already committed.
    Prepared and committed markers both finish as committed: dest stays,
    provision backups go away, ``migrating`` is cleared.
    """
    data = load_inventory(plugin_id)
    changed = False
    for loc in (data.get("locations") or {}).values():
        if not loc:
            continue
        marker = loc.get("migrating")
        if not marker:
            continue
        backup = parse_optional_absolute(marker.get("backup_path"))
        if backup is not None:
            try:
                _remove_path(backup)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Could not remove committed provision backup %s",
                    backup,
                    exc_info=True,
                )
        loc["migrating"] = None
        changed = True
    if changed:
        save_inventory(plugin_id, data)


def _recover_one_migrating_location(
    dest_key: str,
    loc: dict[str, Any],
    keep_new: bool,
) -> bool:
    """Finish or restore one migrating location. True if inventory changed."""
    marker = loc.get("migrating")
    if not marker:
        return False
    if marker.get("status") == "committed" or keep_new:
        backup = parse_optional_absolute(marker.get("backup_path"))
        if backup is not None:
            _remove_path(backup)
        loc["migrating"] = None
        return True
    backup = parse_optional_absolute(marker.get("backup_path"))
    dest = parse_optional_absolute(dest_key)
    if dest is None:
        loc["migrating"] = None
        return True
    if backup is not None:
        _restore_backup(backup, dest)
    loc["version"] = marker.get("prev_version")
    loc["migrating"] = None
    hashes = marker.get("prev_factory_hashes") or {}
    loc["files"] = {
        rel: {"factory_hash": digest} for rel, digest in hashes.items()
    }
    loc.pop("pending_factory", None)
    return True


def _provision_ids_to_recover(plugin_id: str | None) -> list[str]:
    if plugin_id is not None:
        return [plugin_id]
    from ..constant import WORKING_DIR

    if not Path(WORKING_DIR).joinpath("plugin_provisions").is_dir():
        return []
    return [p.stem for p in provisions_dir().glob("*.json")]


def _recover_plugin_migrating_inventory(item_id: str) -> bool:
    """Recover one plugin's migrating locations. True if inventory changed."""
    from .updates import update_is_committed

    keep_new = update_is_committed(item_id)
    data = load_inventory(item_id)
    changed = False
    for dest_key, loc in list((data.get("locations") or {}).items()):
        if not loc:
            continue
        try:
            if _recover_one_migrating_location(dest_key, loc, keep_new):
                changed = True
        except (OSError, shutil.Error):
            logger.exception(
                "Could not recover provision location %s "
                "for '%s'; leaving migrating marker",
                dest_key,
                item_id,
            )
    if not changed:
        return False
    save_inventory(item_id, data)
    if keep_new:
        logger.info(
            "Finished committed provision migration for plugin '%s'",
            item_id,
        )
    else:
        logger.warning(
            "Restored in-progress provision migration for plugin '%s'",
            item_id,
        )
    return True


def recover_migrating_inventory(
    plugin_id: str | None = None,
    *,
    owns_commit=None,
) -> list[str]:
    """Restore any location still marked migrating. Returns plugin ids."""
    recovered: list[str] = []
    for item_id in _provision_ids_to_recover(plugin_id):
        if owns_commit is not None and not owns_commit(item_id):
            continue
        try:
            if _recover_plugin_migrating_inventory(item_id):
                recovered.append(item_id)
        except (OSError, shutil.Error):
            logger.exception(
                "Could not recover provision inventory for '%s'; "
                "continuing",
                item_id,
            )
    return recovered


def _restore_backup(backup: Path, dest: Path) -> None:
    """Replace *dest* with *backup* if the backup still exists."""
    if not backup.exists():
        return
    dest_resolved = ensure_deletable(dest, purpose="restore provision dest")
    if dest_resolved.exists():
        _remove_path(dest_resolved)
    if backup.is_dir():
        shutil.copytree(backup, dest_resolved)
        _remove_path(backup)
        return
    dest_resolved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, dest_resolved)
    _remove_path(backup)


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


def merge_tool_factory(
    factory: dict[str, Any],
    current: dict[str, Any] | None,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge one BuiltinToolConfig by field ownership without I/O."""
    merged = dict(factory)
    prev = previous or {}
    if current:
        for field_name in _PLUGIN_OWNED_TOOL_FIELDS:
            if field_name in current and field_name in prev:
                if current.get(field_name) != prev.get(field_name):
                    merged[field_name] = current[field_name]
            elif field_name in current and field_name not in prev:
                merged[field_name] = current[field_name]
        for field_name in _USER_OWNED_TOOL_FIELDS:
            if field_name in current:
                merged[field_name] = current[field_name]
    return merged


def snapshot_tool_inventory(plugin_id: str) -> dict[str, Any]:
    """Return a copy of persisted tool rows before an activate transaction."""
    tools = load_inventory(plugin_id).get("tools") or {}
    return {
        name: dict(row)
        for name, row in tools.items()
        if name and isinstance(row, dict)
    }


def rollback_uncommitted_tools(
    plugin_id: str,
    before: dict[str, Any],
) -> list[str]:
    """Restore tool inventory to *before* and return names created after it."""
    data = load_inventory(plugin_id)
    now = data.get("tools") or {}
    new_names = [name for name in now if name and name not in before]
    data["tools"] = {
        name: dict(row)
        for name, row in before.items()
        if name and isinstance(row, dict)
    }
    save_inventory(plugin_id, data)
    return new_names


def snapshot_location_keys(plugin_id: str) -> set[str]:
    """Return dest keys present before an activate transaction."""
    return {
        key
        for key in (load_inventory(plugin_id).get("locations") or {})
        if key
    }


def rollback_created_locations(
    plugin_id: str,
    before_keys: set[str],
) -> list[str]:
    """Delete dests created after *before_keys*; leave migrate to recover."""
    data = load_inventory(plugin_id)
    locations = data.get("locations") or {}
    created = [
        key for key in list(locations) if key and key not in before_keys
    ]
    for dest_key in created:
        dest = parse_optional_absolute(dest_key)
        if dest is not None:
            _remove_path(dest)
        locations.pop(dest_key, None)
    if created:
        data["locations"] = locations
        save_inventory(plugin_id, data)
    return created


def tool_names_written_this_txn(
    plugin_id: str,
    before: dict[str, Any],
) -> set[str]:
    """Names ``apply_tool_factory`` wrote during the current activate."""
    now = load_inventory(plugin_id).get("tools") or {}
    written: set[str] = set()
    for name, row in now.items():
        if not name or not isinstance(row, dict):
            continue
        if name not in before:
            written.add(name)
        elif row.get("pending_factory") is not None:
            written.add(name)
    return written


def drop_tool_rows(plugin_id: str, names: list[str]) -> None:
    """Remove inventory tool rows after agent.json has been updated."""
    if not names:
        return
    data = load_inventory(plugin_id)
    tools = data.get("tools") or {}
    changed = False
    for name in names:
        if name in tools:
            tools.pop(name, None)
            changed = True
    if changed:
        data["tools"] = tools
        save_inventory(plugin_id, data)


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
    row = tools.get(tool_name) or {}
    previous = row.get("factory") or {}
    merged = merge_tool_factory(factory, current, previous)
    if not previous:
        tools[tool_name] = {"factory": dict(factory)}
    else:
        tools[tool_name] = {
            "factory": dict(previous),
            "pending_factory": dict(factory),
        }
    save_inventory(plugin_id, data)
    return merged


# pylint: disable=too-many-branches
def commit_migrations(plugin_id: str) -> bool:
    """Persist committed state first, then delete leftover backups.

    Returns True once committed has been persisted (or there was
    nothing to persist). Exceptions after that persist are logged;
    callers must not treat them as an uncommitted activate.
    """
    data = load_inventory(plugin_id)
    changed = False
    backups: list[Path] = []
    for loc in (data.get("locations") or {}).values():
        if not loc:
            continue
        marker = loc.get("migrating")
        if not marker:
            continue
        backup = parse_optional_absolute(marker.get("backup_path"))
        if backup is not None:
            backups.append(backup)
        loc["migrating"] = {
            **marker,
            "status": "committed",
        }
        changed = True
    for tool_name, row in list((data.get("tools") or {}).items()):
        pending = (row or {}).get("pending_factory")
        if pending is None:
            continue
        row["factory"] = dict(pending)
        row.pop("pending_factory", None)
        data["tools"][tool_name] = row
        changed = True
    if changed:
        save_inventory(plugin_id, data)
    try:
        for loc in (data.get("locations") or {}).values():
            marker = (loc or {}).get("migrating") or {}
            if marker.get("status") != "committed":
                continue
            loc["migrating"] = None
        for backup in backups:
            try:
                _remove_path(backup)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Could not remove committed provision backup %s",
                    backup,
                    exc_info=True,
                )
        if changed:
            save_inventory(plugin_id, data)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Post-commit provision cleanup failed for '%s'",
            plugin_id,
            exc_info=True,
        )
    return True


def snapshot_created_dests(plugin_id: str) -> list[str]:
    """Return dest keys this plugin owns (uninstall recheck snapshot)."""
    data = load_inventory(plugin_id)
    dests: list[str] = []
    for dest_key, loc in (data.get("locations") or {}).items():
        if location_owned(loc):
            dests.append(dest_key)
    return dests


def leftover_dests(dests: list[str]) -> list[str]:
    """Return snapshot dests that are still on disk."""
    leftover: list[str] = []
    for dest in dests:
        path = parse_optional_absolute(dest)
        if path is not None and path.exists():
            leftover.append(dest)
    return leftover


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
        dest = parse_optional_absolute(dest_key)
        if dest is None:
            continue
        _remove_path(dest)


def undo_created_locations(plugin_id: str, dests: list[str]) -> None:
    """Remove only destinations created during the current failed load."""
    if not dests:
        return
    data = load_inventory(plugin_id)
    locations = data.get("locations") or {}
    wanted = {item for item in dests if str(item).strip()}
    for dest_key in list(locations):
        if dest_key not in wanted:
            continue
        dest = parse_optional_absolute(dest_key)
        if dest is not None:
            _remove_path(dest)
        locations.pop(dest_key, None)
    save_inventory(plugin_id, data)


def teardown_created_locations(plugin_id: str) -> None:
    """Remove destinations owned by this plugin (uninstall only)."""
    data = load_inventory(plugin_id)
    for dest_key, loc in list((data.get("locations") or {}).items()):
        if not location_owned(loc):
            continue
        dest = parse_optional_absolute(dest_key)
        if dest is None:
            continue
        _remove_path(dest)
    delete_inventory(plugin_id)

# -*- coding: utf-8 -*-
"""On-disk provision inventory and ``provision_files``."""

from __future__ import annotations

import asyncio
import inspect
import hashlib
import importlib
import importlib.util
import json
import logging
import os
import shutil
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Awaitable, Iterator

from ..utils.io_utils import write_json_atomic
from .module_isolation import PluginNamespaceFinder, build_plugin_builtins
from .safe_fs import ensure_deletable, parse_optional_absolute, safe_remove
from .updates import RecoveryResult

logger = logging.getLogger(__name__)


class MigrationRecoveryError(OSError):
    """Uncommitted files could not be restored; keep recovery locations."""

    def __init__(self, result: RecoveryResult) -> None:
        super().__init__("; ".join(result.failures.values()))
        self.result = result


def provisions_dir() -> Path:
    """Return the inventory directory (created on demand)."""
    from ..constant import WORKING_DIR

    path = Path(WORKING_DIR) / "plugin_provisions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def inventory_path(plugin_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in plugin_id)
    return provisions_dir() / f"{safe}.json"


def load_inventory(plugin_id: str, *, strict: bool = False) -> dict[str, Any]:
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
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            message = (
                f"Cannot read provision inventory for '{plugin_id}': {exc}"
            )
            raise OSError(message) from exc
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
    row = next((item for item in rows if item.get("desc") == desc), None)
    if row is None:
        row = {"desc": desc, "kind": kind or "escape"}
        rows.append(row)
    # A plugin upgrade can add restartable cleanup for an existing provision.
    # Keep its ownership and do not rerun setup or erase an existing locator.
    if teardown_ref:
        row["teardown_ref"] = teardown_ref
    if kind and kind != "escape":
        row["kind"] = kind
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


class EscapeRollbackError(RuntimeError):
    """Cleanup failed; persistent rows and callable handles must survive."""

    def __init__(self, errors: list[str], failed_descs: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.failed_descs = failed_descs


def undo_this_txn_escapes(
    plugin_id: str,
    escapes: list[tuple[str, Any]],
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Undo this-txn escape rows and drop those inventory rows.

    ``teardown`` runs only when this transaction actually ran
    ``setup``. A ``None`` teardown only drops the newly written
    inventory row. Existing rows that did not run ``setup`` in this
    transaction are left alone.
    """
    errors: list[str] = []
    failed_descs: list[str] = []
    for desc, teardown in reversed(list(escapes)):
        try:
            if teardown is not None:
                if loop is not None:
                    # Invoke on the lifecycle loop: even a sync callback
                    # can create a Task or return a loop-bound Future.
                    asyncio.run_coroutine_threadsafe(
                        _invoke_teardown(teardown),
                        loop,
                    ).result()
                else:
                    result = teardown()
                    if inspect.isawaitable(result):
                        asyncio.run(_await_teardown(result))
            drop_escape_provision(plugin_id, desc)
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
            reason = str(exc) or type(exc).__name__
            errors.append(f"provision {desc}: {reason}")
            failed_descs.append(desc)
            logger.exception(
                "This-txn escape teardown %r failed for '%s'",
                desc,
                plugin_id,
            )
    if errors:
        raise EscapeRollbackError(errors, failed_descs)


async def _invoke_teardown(callback) -> None:
    result = callback()
    if inspect.isawaitable(result):
        await result


def replay_persisted_provisions(
    plugin_id: str,
    source_path: Path | None,
) -> list[str]:
    """Replay persisted cleanup, retaining unresolved rows for retry."""
    data = load_inventory(plugin_id)
    errors: list[str] = []
    for row in data.get("provisions") or []:
        if not isinstance(row, dict):
            continue
        ref = str(row.get("teardown_ref") or "").strip()
        kind = str(row.get("kind") or "")
        if kind == "cloudpaw_agents" and not ref:
            ref = "agents_setup:uninstall_agents"
        desc = str(row.get("desc") or kind or "unknown provision")
        if not ref:
            errors.append(f"candidate: {desc}: no restartable teardown")
            continue
        try:
            _call_teardown_ref(source_path, ref)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"provision {desc}: {exc}")
            continue
        drop_escape_provision(plugin_id, str(row.get("desc") or ""))
    return errors


def _call_teardown_ref(source_path: Path | None, ref: str) -> None:
    module_name, _, func_name = ref.partition(":")
    if not all(part.isidentifier() for part in module_name.split(".")) or not (
        func_name.isidentifier()
    ):
        raise ValueError(f"Invalid teardown reference: {ref}")
    with _teardown_module(source_path, module_name) as module:
        callback = getattr(module, func_name, None)
        if not callable(callback):
            raise RuntimeError(f"Teardown {ref} is not callable")
        result = callback()
        if inspect.isawaitable(result):
            asyncio.run(_await_teardown(result))


@contextmanager
def _teardown_module(
    source_path: Path | None,
    module_name: str,
) -> Iterator[ModuleType]:
    """Import cleanup in a fresh package without running the plugin entry."""
    if source_path is None:
        yield importlib.import_module(module_name)
        return
    root = source_path.resolve(strict=True)
    top = root / module_name.split(".", 1)[0]
    if not any(
        path.exists() or path.is_symlink()
        for path in (top, top.with_suffix(".py"))
    ):
        yield importlib.import_module(module_name)
        return
    candidate = root.joinpath(*module_name.split("."))
    for path in (
        candidate,
        candidate.with_suffix(".py"),
        candidate / "__init__.py",
    ):
        if not path.resolve().is_relative_to(root):
            raise ValueError(
                f"Teardown module is outside plugin source: {module_name}",
            )
    namespace = f"plugin_teardown_{uuid.uuid4().hex}"
    package = ModuleType(namespace)
    package.__path__ = [str(root)]
    package.__package__ = namespace
    package.__spec__ = importlib.machinery.ModuleSpec(
        namespace,
        loader=None,
        is_package=True,
    )
    finder = PluginNamespaceFinder()
    finder.register(namespace, build_plugin_builtins(namespace, [str(root)]))
    previous_paths = set(sys.path)
    sys.modules[namespace] = package
    sys.meta_path.insert(0, finder)
    try:
        yield importlib.import_module(f"{namespace}.{module_name}")
    finally:
        sys.meta_path.remove(finder)
        finder.unregister(namespace)
        for name in list(sys.modules):
            if name == namespace or name.startswith(namespace + "."):
                sys.modules.pop(name, None)
        sys.path[:] = [
            entry
            for entry in sys.path
            if entry in previous_paths
            or not os.path.isabs(entry)
            or not Path(entry).resolve().is_relative_to(root)
        ]


async def _await_teardown(result: Awaitable[Any]) -> None:
    """Adapt any awaitable cleanup result to asyncio.run's coroutine input."""
    await result


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


class PostCommitCleanupError(OSError):
    """Cleanup failed after durable commit; the new version must stay."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _cleanup_committed_migrations(
    plugin_id: str,
    data: dict[str, Any],
) -> None:
    errors: list[str] = []
    changed = False
    for dest_key, loc in (data.get("locations") or {}).items():
        marker = (loc or {}).get("migrating")
        if not marker:
            continue
        try:
            _remove_path(parse_optional_absolute(marker.get("backup_path")))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"committed provision backup {dest_key}: {exc}")
            continue
        loc["migrating"] = None
        changed = True
    if changed:
        try:
            save_inventory(plugin_id, data)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"committed provision inventory: {exc}")
    if errors:
        raise PostCommitCleanupError(errors)


def _mark_migrations_committed(data: dict[str, Any]) -> bool:
    """Mark location migrations committed before removing their backups."""
    changed = False
    for loc in (data.get("locations") or {}).values():
        marker = (loc or {}).get("migrating")
        if marker and marker.get("status") != "committed":
            loc["migrating"] = {**marker, "status": "committed"}
            changed = True
    return changed


def commit_prepared_migrations(plugin_id: str) -> None:
    """Keep new dests and backup locators until cleanup succeeds."""
    data = load_inventory(plugin_id, strict=True)
    changed = _mark_migrations_committed(data)
    if changed:
        save_inventory(plugin_id, data)
    _cleanup_committed_migrations(plugin_id, data)


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


def _recover_plugin_migrating_inventory(
    item_id: str,
    result: RecoveryResult,
) -> bool:
    """Recover one plugin's migrating locations. True if inventory changed."""
    from .updates import update_is_committed

    keep_new = update_is_committed(item_id)
    data = load_inventory(item_id, strict=True)
    committed = keep_new or all(
        (loc.get("migrating") or {}).get("status") == "committed"
        for loc in (data.get("locations") or {}).values()
        if loc and loc.get("migrating")
    )
    changed = False
    for dest_key, loc in list((data.get("locations") or {}).items()):
        if not loc:
            continue
        try:
            if _recover_one_migrating_location(dest_key, loc, keep_new):
                changed = True
        except (OSError, shutil.Error) as exc:
            result.fail(
                item_id,
                exc,
                committed=keep_new
                or (loc.get("migrating") or {}).get("status") == "committed",
            )
            logger.exception(
                "Could not recover provision location %s "
                "for '%s'; leaving migrating marker",
                dest_key,
                item_id,
            )
    if not changed:
        return False
    try:
        save_inventory(item_id, data)
    except (OSError, shutil.Error) as exc:
        result.fail(item_id, exc, committed=committed)
        return False
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
    raise_on_blocked: bool = False,
) -> RecoveryResult:
    """Restore migrations; transactions must stop on blocked recovery."""
    from .updates import update_is_committed

    recovered = RecoveryResult()
    for item_id in _provision_ids_to_recover(plugin_id):
        if owns_commit is not None and not owns_commit(item_id):
            continue
        try:
            if _recover_plugin_migrating_inventory(item_id, recovered):
                recovered.append(item_id)
        except (OSError, shutil.Error) as exc:
            recovered.fail(
                item_id,
                exc,
                committed=update_is_committed(item_id),
            )
            logger.exception(
                "Could not recover provision inventory for '%s'; "
                "continuing",
                item_id,
            )
    if raise_on_blocked and recovered.blocked:
        raise MigrationRecoveryError(recovered)
    return recovered


def _restore_backup(backup: Path, dest: Path) -> None:
    """Replace *dest* with *backup* if the backup still exists."""
    if not backup.exists():
        return
    dest = ensure_deletable(dest, purpose="restore provision dest")
    _remove_path(dest)
    if backup.is_dir():
        shutil.copytree(backup, dest)
        _remove_path(backup)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, dest)
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
    """Drop new inventory rows; delete only owned dests, not user paths."""
    data = load_inventory(plugin_id)
    locations = data.get("locations") or {}
    created = [
        key for key in list(locations) if key and key not in before_keys
    ]
    for dest_key in created:
        dest = parse_optional_absolute(dest_key)
        if dest is not None and location_owned(locations[dest_key]):
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


def commit_migrations(plugin_id: str) -> bool:
    """Persist commit before cleanup; post-commit failures cannot roll back."""
    data = load_inventory(plugin_id, strict=True)
    changed = _mark_migrations_committed(data)
    for row in (data.get("tools") or {}).values():
        pending = (row or {}).get("pending_factory")
        if pending is not None:
            row["factory"] = dict(pending)
            row.pop("pending_factory", None)
            changed = True
    if changed:
        save_inventory(plugin_id, data)
    _cleanup_committed_migrations(plugin_id, data)
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

# -*- coding: utf-8 -*-
"""Read-only source fingerprinting and review-plan construction."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..utils.io_utils import run_sync_io
from .models import (
    MigrationAssetPlan,
    MigrationPlan,
    ProviderInventory,
)
from .selection import bound_mcp_plugin
from .skill_transfer import read_regular_file

_MAX_FINGERPRINT_ENTRIES = 6_000
_MAX_FINGERPRINT_FILES = 5_000
_MAX_FINGERPRINT_BYTES = 64 * 1024 * 1024
_TOOL_FIELDS = (
    ("memory", "memory_projects"),
    ("cron", "scheduled_tasks"),
    ("skills", "skills"),
    ("mcp", "mcp_servers"),
    ("plugins", "plugins"),
)


@dataclass
class _FingerprintBudget:
    entries: int = 0
    files: int = 0
    total_bytes: int = 0

    def add_entry(self, path: Path) -> None:
        self.entries += 1
        if self.entries > _MAX_FINGERPRINT_ENTRIES:
            raise ValueError(
                "Portable source tree exceeds the fingerprint entry limit "
                f"({_MAX_FINGERPRINT_ENTRIES}): {path}",
            )

    def add_file(self, path: Path, size: int) -> None:
        self.files += 1
        if self.files > _MAX_FINGERPRINT_FILES:
            raise ValueError(
                "Portable source tree exceeds the fingerprint file limit "
                f"({_MAX_FINGERPRINT_FILES}): {path}",
            )
        if size < 0 or self.total_bytes + size > _MAX_FINGERPRINT_BYTES:
            raise ValueError(
                "Portable source tree exceeds the fingerprint byte limit "
                f"({_MAX_FINGERPRINT_BYTES}): {path}",
            )
        self.total_bytes += size


def _fingerprint_error(path: Path, reason: str) -> ValueError:
    return ValueError(f"Unsafe portable fingerprint source {path}: {reason}")


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return Path(os.path.abspath(expanded))
    return Path(os.path.abspath(Path.cwd() / expanded))


def _hash_record(hasher: Any, kind: str, value: str) -> None:
    encoded_kind = kind.encode("utf-8")
    encoded_value = value.encode("utf-8", errors="replace")
    hasher.update(len(encoded_kind).to_bytes(4, "big"))
    hasher.update(encoded_kind)
    hasher.update(len(encoded_value).to_bytes(8, "big"))
    hasher.update(encoded_value)


def _lstat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise _fingerprint_error(
            path,
            f"cannot inspect ({type(exc).__name__})",
        ) from exc


def _resolved_within(path: Path, root: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise _fingerprint_error(
            path,
            "path escapes its declared root",
        ) from exc
    return resolved


def _hash_regular_file(
    hasher: Any,
    path: Path,
    budget: _FingerprintBudget,
) -> None:
    before = _lstat(path)
    if stat.S_ISLNK(before.st_mode):
        raise _fingerprint_error(path, "symbolic links are not allowed")
    if not stat.S_ISREG(before.st_mode):
        raise _fingerprint_error(path, "entry is not a regular file")

    budget.add_file(path, before.st_size)
    try:
        data = read_regular_file(path, expected=before)
    except ValueError as exc:
        raise _fingerprint_error(path, str(exc)) from exc
    except OSError as exc:
        raise _fingerprint_error(
            path,
            f"cannot read ({type(exc).__name__})",
        ) from exc
    _hash_record(hasher, "file", str(path))
    hasher.update(len(data).to_bytes(8, "big"))
    hasher.update(data)


def _hash_tree(
    hasher: Any,
    root: Path,
    budget: _FingerprintBudget,
) -> None:
    root_info = _lstat(root)
    if stat.S_ISLNK(root_info.st_mode):
        raise _fingerprint_error(root, "symbolic links are not allowed")
    if not stat.S_ISDIR(root_info.st_mode):
        raise _fingerprint_error(root, "skill/plugin root is not a directory")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise _fingerprint_error(root, "cannot resolve source root") from exc

    budget.add_entry(resolved_root)
    pending = [resolved_root]
    while pending:
        path = pending.pop()
        info = _lstat(path)
        if stat.S_ISLNK(info.st_mode):
            _hash_record(hasher, "rejected-symbolic-link", str(path))
            continue
        _resolved_within(path, resolved_root)
        if stat.S_ISREG(info.st_mode):
            _hash_regular_file(hasher, path, budget)
            continue
        if not stat.S_ISDIR(info.st_mode):
            _hash_record(hasher, "rejected-non-regular-entry", str(path))
            continue

        _hash_record(hasher, "directory", str(path))
        children: list[Path] = []
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    child = Path(entry.path)
                    budget.add_entry(child)
                    children.append(child)
        except OSError as exc:
            raise _fingerprint_error(
                path,
                f"cannot scan directory ({type(exc).__name__})",
            ) from exc
        children.sort(key=lambda child: child.name)
        pending.extend(reversed(children))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _has_parent_in(path: Path, roots: set[Path]) -> bool:
    parent = path.parent
    while parent != parent.parent:
        if parent in roots:
            return True
        parent = parent.parent
    return parent in roots


@dataclass(frozen=True)
class _FingerprintSource:
    kind: str
    path: Path


def _fingerprint_sources(
    inventory: ProviderInventory,
) -> list[_FingerprintSource]:
    sources: list[_FingerprintSource] = []

    def add(kind: str, value: Path | str) -> None:
        if len(sources) >= _MAX_FINGERPRINT_ENTRIES:
            raise ValueError(
                "Portable inventory exceeds the fingerprint source limit "
                f"({_MAX_FINGERPRINT_ENTRIES}).",
            )
        sources.append(
            _FingerprintSource(kind=kind, path=_absolute_path(Path(value))),
        )

    for project in inventory.memory_projects:
        for item in project.files:
            relative = item.relative_path
            if relative.is_absolute() or ".." in relative.parts:
                raise _fingerprint_error(
                    item.source_path,
                    "memory relative path escapes its declared scope",
                )
            add("file", item.source_path)
    for skill in inventory.skills:
        add("tree", skill.directory)
    for plugin in inventory.plugins:
        if plugin.install_source:
            add("plugin", plugin.install_source)
    return sources


# pylint: disable-next=too-many-return-statements
def _canonical_source(
    source: _FingerprintSource,
) -> tuple[str, Path]:
    path = source.path
    try:
        info = path.lstat()
    except FileNotFoundError:
        if source.kind == "plugin":
            return "external", path
        return "rejected-missing", path
    except OSError as exc:
        raise _fingerprint_error(
            path,
            f"cannot inspect ({type(exc).__name__})",
        ) from exc

    if stat.S_ISLNK(info.st_mode):
        return "rejected-symbolic-link", path
    if source.kind == "tree" and not stat.S_ISDIR(info.st_mode):
        return "rejected-non-directory", path
    if source.kind == "file" and not stat.S_ISREG(info.st_mode):
        return "rejected-non-regular", path
    if source.kind == "plugin" and not (
        stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
    ):
        return "rejected-non-regular", path
    if source.kind == "file":
        return "file", path
    try:
        canonical = path.resolve(strict=True)
    except OSError as exc:
        raise _fingerprint_error(path, "cannot resolve source") from exc
    return ("tree" if stat.S_ISDIR(info.st_mode) else "file"), canonical


def _hash_inventory_sources(
    hasher: Any,
    inventory: ProviderInventory,
    file_payloads: dict[Path, bytes] | None = None,
) -> None:
    classified = set()
    for source in _fingerprint_sources(inventory):
        if source.kind == "file" and file_payloads is not None:
            try:
                file_payloads[source.path]
            except KeyError as exc:
                raise _fingerprint_error(
                    source.path,
                    "memory snapshot is unavailable",
                ) from exc
            classified.add(("snapshot", source.path))
        else:
            classified.add(_canonical_source(source))
    roots = sorted(
        (path for kind, path in classified if kind == "tree"),
        key=lambda path: path.parts,
    )
    selected_roots: list[Path] = []
    for root in roots:
        if selected_roots and _is_within(root, selected_roots[-1]):
            continue
        selected_roots.append(root)

    root_set = set(selected_roots)
    files = {
        (kind, path)
        for kind, path in classified
        if kind in {"file", "snapshot"} and not _has_parent_in(path, root_set)
    }
    markers = {(kind, path) for kind, path in classified if _is_marker(kind)}
    work = [("tree", path) for path in selected_roots]
    work.extend(files)
    work.extend(markers)
    work.sort(key=lambda item: (str(item[1]), item[0]))

    budget = _FingerprintBudget()
    for kind, path in work:
        if kind == "tree":
            _hash_tree(hasher, path, budget)
        elif kind == "file":
            budget.add_entry(path)
            _hash_regular_file(hasher, path, budget)
        elif kind == "snapshot":
            data = file_payloads[path] if file_payloads is not None else b""
            budget.add_entry(path)
            budget.add_file(path, len(data))
            _hash_record(hasher, "file", str(path))
            hasher.update(len(data).to_bytes(8, "big"))
            hasher.update(data)
        else:
            budget.add_entry(path)
            _hash_record(hasher, kind, str(path))


def _is_marker(kind: str) -> bool:
    return kind not in {"tree", "file", "snapshot"}


def inventory_fingerprint(
    inventory: ProviderInventory,
    *,
    file_payloads: dict[Path, bytes] | None = None,
) -> str:
    """Fingerprint normalized objects plus referenced portable file bytes."""
    hasher = hashlib.sha256()
    payload = inventory.model_dump(
        mode="json",
        exclude={
            "ignored_session_ids",
            "warnings",
        },
    )
    hasher.update(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    _hash_inventory_sources(hasher, inventory, file_payloads)
    return hasher.hexdigest()


def tool_asset_fingerprints(
    inventory: ProviderInventory,
    *,
    file_payloads: dict[Path, bytes] | None = None,
) -> dict[str, str]:
    """Fingerprint selected tools without mutable conversation history."""
    updates = {field: [] for _kind, field in _TOOL_FIELDS} | {
        "sessions": [],
        "ignored_session_ids": [],
        "marketplaces": [],
        "warnings": [],
    }
    empty = inventory.model_copy(update=updates)
    marketplaces: dict[str, list[Any]] = {}
    for marketplace in inventory.marketplaces:
        keys = (
            (marketplace.source_id,)
            if marketplace.source_id == marketplace.name
            else (marketplace.source_id, marketplace.name)
        )
        for key in keys:
            marketplaces.setdefault(key, []).append(marketplace)
    bound_mcps: dict[str, list[Any]] = {}
    for server in inventory.mcp_servers:
        if plugin_id := bound_mcp_plugin(server):
            bound_mcps.setdefault(plugin_id, []).append(server)

    result = {}
    for kind, field in _TOOL_FIELDS:
        for item in getattr(inventory, field):
            scoped = empty.model_copy(
                update={
                    field: [item],
                    "marketplaces": (
                        marketplaces.get(item.marketplace, [])
                        if kind == "plugins"
                        else []
                    ),
                    "mcp_servers": (
                        bound_mcps.get(item.source_id, [])
                        if kind == "plugins"
                        else [item]
                        if field == "mcp_servers"
                        else []
                    ),
                },
            )
            result[f"{kind}:{item.source_id}"] = inventory_fingerprint(
                scoped,
                file_payloads=file_payloads if kind == "memory" else None,
            )
    return result


_PLAN_TYPES = (
    ("sessions", "session"),
    ("memory_projects", "memory"),
    ("skills", "skill"),
    ("mcp_servers", "mcp"),
    ("plugins", "plugin"),
    ("scheduled_tasks", "scheduled_task"),
)


def _build_migration_plan(
    agent_id: str,
    inventory: ProviderInventory,
) -> MigrationPlan:
    """Build a selectable plan without changing runtime assets."""
    actions = []
    for collection, asset_type in _PLAN_TYPES:
        for item in getattr(inventory, collection):
            if asset_type == "mcp" and bound_mcp_plugin(item):
                continue
            actions.append(
                MigrationAssetPlan(
                    asset_type=asset_type,
                    source_id=item.source_id,
                    name=(
                        getattr(item, "project_key", "")
                        or getattr(item, "title", "")
                        or item.name
                    ),
                    requires_sessions=(
                        asset_type == "scheduled_task"
                        and str(
                            item.metadata.get("source_kind") or "",
                        ).lower()
                        == "heartbeat"
                    ),
                ),
            )
    return MigrationPlan(
        plan_id=f"plan-{uuid4().hex}",
        source=inventory.provider_id,
        agent_id=agent_id,
        created_at=datetime.now(timezone.utc),
        asset_fingerprints=tool_asset_fingerprints(inventory),
        actions=actions,
    )


async def build_migration_plan(
    workspace: Any,
    inventory: ProviderInventory,
) -> MigrationPlan:
    """Build a selectable plan without blocking the event loop."""
    return await run_sync_io(
        _build_migration_plan,
        workspace.agent_id,
        inventory,
    )


__all__ = [
    "build_migration_plan",
    "inventory_fingerprint",
    "tool_asset_fingerprints",
]

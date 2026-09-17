# -*- coding: utf-8 -*-
"""将旧 Agent workspace 记忆原地登记为公共记忆。"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MEMORY_SCOPE_MANIFEST = "migrations/memory_scope_public.json"
_MEMORY_ROOT_FILES = ("MEMORY.md",)
_MEMORY_DIRECTORIES = ("memory", "daily", "digest")
_INDEX_METADATA_NAMES = frozenset(
    {"index.json", "manifest.json", "metadata.json", "status.json"}
)


@dataclass(frozen=True, slots=True)
class MemoryScopeMigrationResult:
    changed: bool
    registered_agents: int
    registered_files: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_workspace(workspace: Path) -> tuple[list[dict[str, Any]], list[str]]:
    memory_files: list[Path] = []
    metadata_files: list[Path] = []
    for filename in _MEMORY_ROOT_FILES:
        candidate = workspace / filename
        if candidate.is_file() and not candidate.is_symlink():
            memory_files.append(candidate)
    for dirname in _MEMORY_DIRECTORIES:
        root = workspace / dirname
        if not root.is_dir() or root.is_symlink():
            continue
        for candidate in sorted(root.rglob("*")):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            if candidate.suffix.lower() == ".md":
                memory_files.append(candidate)
            elif candidate.name.lower() in _INDEX_METADATA_NAMES:
                metadata_files.append(candidate)
    ordered_memory_files = sorted(
        set(memory_files),
        key=lambda path: path.relative_to(workspace).as_posix(),
    )
    files = [
        {
            "path": path.relative_to(workspace).as_posix(),
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
        for path in ordered_memory_files
    ]
    metadata = [
        path.relative_to(workspace).as_posix()
        for path in sorted(
            set(metadata_files),
            key=lambda item: item.relative_to(workspace).as_posix(),
        )
    ]
    return files, metadata


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "agents": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Ignoring invalid memory scope migration manifest: %s", path)
        return {"version": 1, "agents": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("agents"), dict):
        return {"version": 1, "agents": {}}
    return payload


def _write_manifest_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def migrate_legacy_memory_scopes(
    *,
    working_dir: Path,
    agent_workspaces: Mapping[str, Path],
    load_agent: Callable[[str], Any],
    save_agent: Callable[[str, Any], None],
) -> MemoryScopeMigrationResult:
    """扫描旧记忆并原地登记；正文和旧索引都不移动、不删除。"""
    manifest_path = working_dir / MEMORY_SCOPE_MANIFEST
    manifest = _read_manifest(manifest_path)
    agents = manifest.setdefault("agents", {})
    changed_agents = 0
    changed_files = 0

    for agent_id, raw_workspace in sorted(agent_workspaces.items()):
        workspace = Path(raw_workspace).expanduser()
        if not workspace.is_dir() or workspace.is_symlink():
            continue
        files, metadata = _scan_workspace(workspace)
        if not files and not metadata:
            continue
        previous = agents.get(agent_id)
        comparable = {
            "scope": "public",
            "workspace_key": workspace.relative_to(working_dir).as_posix()
            if workspace.is_relative_to(working_dir)
            else str(workspace),
            "index_state": "needs_reindex",
            "files": files,
            "legacy_index_metadata": metadata,
        }
        previous_comparable = (
            {key: previous.get(key) for key in comparable}
            if isinstance(previous, dict)
            else None
        )
        if previous_comparable != comparable:
            old_files = {
                (item.get("path"), item.get("sha256"))
                for item in (previous or {}).get("files", [])
                if isinstance(item, dict)
            }
            changed_files += sum(
                (item["path"], item["sha256"]) not in old_files for item in files
            )
            agents[agent_id] = {
                **comparable,
                "registered_at": (
                    previous.get("registered_at")
                    if isinstance(previous, dict) and previous.get("registered_at")
                    else datetime.now(UTC).isoformat().replace("+00:00", "Z")
                ),
            }
            changed_agents += 1
            agent_config = load_agent(agent_id)
            memory_config = agent_config.running.reme_light_memory_config
            if not memory_config.needs_reindex:
                memory_config.needs_reindex = True
                save_agent(agent_id, agent_config)

    changed = changed_agents > 0
    if changed:
        _write_manifest_atomic(manifest_path, manifest)
    return MemoryScopeMigrationResult(
        changed=changed,
        registered_agents=changed_agents,
        registered_files=changed_files,
    )

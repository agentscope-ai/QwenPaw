# -*- coding: utf-8 -*-
"""Asset export engine.

Collects workspace assets and packages them as ZIP.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import platform
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from qwenpaw.__version__ import __version__
from qwenpaw.backup.errors import InsufficientStorageError
from qwenpaw.backup.models import (
    AssetEntry,
    AssetManifest,
    AssetType,
    ExportOptions,
    ExportResult,
)
from qwenpaw.backup.sanitizer import sanitize_preferences
from qwenpaw.backup.utils import get_agent_id
from qwenpaw.constant import WORKING_DIR

logger = logging.getLogger(__name__)

_READ_LOCK_TIMEOUT: float = 30.0
_MAX_FILE_READ_RETRIES: int = 3

# Collected assets: (entries, path→bytes map)
_Collected = tuple[list[AssetEntry], dict[str, bytes]]


@runtime_checkable
class MemoryManagerProtocol(Protocol):
    async def acquire_read_lock(
        self,
        timeout: float = _READ_LOCK_TIMEOUT,
    ) -> Any:
        ...

    async def release_read_lock(self, lock: Any) -> None:
        ...


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_read_file(path: Path) -> tuple[bytes, str, bool]:
    """Read with hash-consistency retry. Returns (data, sha256, is_partial)."""
    for attempt in range(_MAX_FILE_READ_RETRIES):
        data1, h1 = path.read_bytes(), None
        h1 = _sha256(data1)
        data2 = path.read_bytes()
        h2 = _sha256(data2)
        if h1 == h2:
            return data1, h1, False
        logger.warning(
            "Hash mismatch for %s (attempt %d/%d)",
            path,
            attempt + 1,
            _MAX_FILE_READ_RETRIES,
        )
    logger.warning("File %s marked as partial after retries", path)
    return data2, h2, True  # type: ignore[possibly-undefined]


def _make_entry(
    asset_type: AssetType,
    name: str,
    rel: str,
    data: bytes,
    sha: str,
    is_partial: bool,
) -> AssetEntry:
    metadata: dict[str, Any] = {"partial": True} if is_partial else {}
    return AssetEntry(
        asset_type=asset_type,
        name=name,
        relative_path=rel,
        sha256=sha,
        size_bytes=len(data),
        metadata=metadata,
    )


class AssetExporter:
    """Collects workspace assets and packages them into a ZIP archive."""

    def __init__(
        self,
        memory_manager: Optional[MemoryManagerProtocol] = None,
    ) -> None:
        self._memory_manager = memory_manager

    def _collect_preferences(self, workspace_dir: Path) -> _Collected:
        entries: list[AssetEntry] = []
        file_data: dict[str, bytes] = {}
        for fname in ("agent.json", "config.json"):
            fpath = workspace_dir / fname
            if not fpath.exists() or fpath.name.startswith(".env"):
                continue
            raw, raw_hash, is_partial = _safe_read_file(fpath)
            rel = f"preferences/{fname}"
            try:
                sanitized = sanitize_preferences(
                    json.loads(raw.decode("utf-8")),
                )
                data = json.dumps(
                    sanitized,
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8")
                sha = _sha256(data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                data, sha, is_partial = raw, raw_hash, True
            file_data[rel] = data
            entries.append(
                _make_entry(
                    AssetType.PREFERENCES,
                    fname,
                    rel,
                    data,
                    sha,
                    is_partial,
                ),
            )
        return entries, file_data

    async def _collect_memories(self, workspace_dir: Path) -> _Collected:
        entries: list[AssetEntry] = []
        file_data: dict[str, bytes] = {}
        memory_dir = workspace_dir / "memory"
        if not memory_dir.exists():
            return entries, file_data

        lock = None
        lock_partial = False
        if self._memory_manager is not None:
            try:
                lock = await asyncio.wait_for(
                    self._memory_manager.acquire_read_lock(
                        timeout=_READ_LOCK_TIMEOUT,
                    ),
                    timeout=_READ_LOCK_TIMEOUT,
                )
            except (asyncio.TimeoutError, Exception) as exc:
                logger.warning(
                    "Memory read lock timeout/error:"
                    " %s — marking as partial",
                    exc,
                )
                lock_partial = True
        try:
            for fpath in sorted(memory_dir.rglob("*")):
                if not fpath.is_file() or fpath.name.startswith(".env"):
                    continue
                data, sha, is_partial = _safe_read_file(fpath)
                mem_rel = fpath.relative_to(
                    workspace_dir,
                ).relative_to("memory")
                rel = f"memories/{mem_rel}"
                file_data[rel] = data
                entries.append(
                    _make_entry(
                        AssetType.MEMORIES,
                        fpath.name,
                        rel,
                        data,
                        sha,
                        is_partial or lock_partial,
                    ),
                )
        finally:
            if lock is not None and self._memory_manager is not None:
                try:
                    await self._memory_manager.release_read_lock(lock)
                except Exception as exc:
                    logger.warning(
                        "Failed to release memory read lock: %s",
                        exc,
                    )
        return entries, file_data

    def _collect_skills(self, workspace_dir: Path) -> _Collected:
        entries: list[AssetEntry] = []
        file_data: dict[str, bytes] = {}
        skills_dir = workspace_dir / "skills"
        if skills_dir.exists():
            self._collect_dir(
                skills_dir,
                "skills",
                AssetType.SKILLS,
                entries,
                file_data,
            )
        manifest_path = workspace_dir / "skill_manifest.json"
        if manifest_path.exists():
            data, sha, is_partial = _safe_read_file(manifest_path)
            rel = "skills/skill_manifest.json"
            file_data[rel] = data
            entries.append(
                _make_entry(
                    AssetType.SKILLS,
                    "skill_manifest.json",
                    rel,
                    data,
                    sha,
                    is_partial,
                ),
            )
        return entries, file_data

    def _collect_tools(self, workspace_dir: Path) -> _Collected:
        entries: list[AssetEntry] = []
        file_data: dict[str, bytes] = {}
        agent_json = workspace_dir / "agent.json"
        if not agent_json.exists():
            return entries, file_data
        raw, _, _ = _safe_read_file(agent_json)
        try:
            tools = json.loads(raw.decode("utf-8")).get("tools")
            if tools is not None:
                data = json.dumps(tools, ensure_ascii=False, indent=2).encode(
                    "utf-8",
                )
                rel = "tools/tools_config.json"
                file_data[rel] = data
                entries.append(
                    _make_entry(
                        AssetType.TOOLS,
                        "tools_config.json",
                        rel,
                        data,
                        _sha256(data),
                        False,
                    ),
                )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning(
                "Failed to parse tools from %s,"
                " skipping tool collection: %s",
                agent_json,
                exc,
            )
        return entries, file_data

    def _collect_dir(
        self,
        base_dir: Path,
        prefix: str,
        asset_type: AssetType,
        entries: list[AssetEntry],
        file_data: dict[str, bytes],
    ) -> None:
        for fpath in sorted(base_dir.rglob("*")):
            if not fpath.is_file() or fpath.name.startswith(".env"):
                continue
            data, sha, is_partial = _safe_read_file(fpath)
            rel = f"{prefix}/{fpath.relative_to(base_dir)}"
            file_data[rel] = data
            entries.append(
                _make_entry(
                    asset_type,
                    fpath.name,
                    rel,
                    data,
                    sha,
                    is_partial,
                ),
            )

    def _collect_global_config(self) -> _Collected:
        """Collect root config.json (provider registrations)."""
        entries: list[AssetEntry] = []
        file_data: dict[str, bytes] = {}
        config_path = WORKING_DIR / "config.json"
        if not config_path.exists():
            return entries, file_data
        raw, raw_hash, is_partial = _safe_read_file(config_path)
        try:
            sanitized = sanitize_preferences(json.loads(raw.decode("utf-8")))
            data = json.dumps(sanitized, ensure_ascii=False, indent=2).encode(
                "utf-8",
            )
            sha = _sha256(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data, sha, is_partial = raw, raw_hash, True
        rel = "global_config/config.json"
        file_data[rel] = data
        entries.append(
            _make_entry(
                AssetType.GLOBAL_CONFIG,
                "config.json",
                rel,
                data,
                sha,
                is_partial,
            ),
        )
        return entries, file_data

    async def export_assets(self, options: ExportOptions) -> ExportResult:
        """Export workspace assets to a ZIP package."""
        ws = options.workspace_dir
        if not ws.exists():
            raise FileNotFoundError(f"Workspace directory not found: {ws}")

        all_entries: list[AssetEntry] = []
        all_data: dict[str, bytes] = {}

        collectors = []
        if options.include_preferences:
            collectors.append(self._collect_preferences(ws))
        if options.include_skills:
            collectors.append(self._collect_skills(ws))
        if options.include_tools:
            collectors.append(self._collect_tools(ws))
        if options.include_global_config:
            collectors.append(self._collect_global_config())
        for entries, fdata in collectors:
            all_entries.extend(entries)
            all_data.update(fdata)

        if options.include_memories:
            entries, fdata = await self._collect_memories(ws)
            all_entries.extend(entries)
            all_data.update(fdata)

        manifest = AssetManifest(
            created_at=datetime.now(timezone.utc).isoformat(),
            source_agent_id=get_agent_id(ws),
            source_device_id=platform.node() or "unknown",
            copaw_version=__version__,
            assets=all_entries,
        )

        output = options.output_path
        if output is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            output = (
                ws.parent
                / f"copaw-assets-{get_agent_id(ws)}-{ts}.copaw-assets.zip"
            )

        estimated = sum(len(d) for d in all_data.values()) + 4096
        try:
            disk = shutil.disk_usage(
                output.parent if output.parent.exists() else ws,
            )
            if disk.free < estimated * 2:
                raise InsufficientStorageError(
                    f"Insufficient disk space: {disk.free}"
                    f" free, need {estimated * 2}",
                )
        except OSError:
            pass

        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest.model_dump_json(indent=2))
            for entry in all_entries:
                data = all_data.get(entry.relative_path)
                if data is not None:
                    zf.writestr(entry.relative_path, data)

        return ExportResult(
            zip_path=output,
            manifest=manifest,
            total_size_bytes=output.stat().st_size,
            asset_count=len(all_entries),
        )

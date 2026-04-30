# -*- coding: utf-8 -*-
"""Backup storage operations: list, detail, delete, export, import."""
from __future__ import annotations

import asyncio
import json
import logging
import zipfile
from pathlib import Path

from .._utils.constants import PREFIX_WORKSPACES, validate_backup_id, zip_path
from .._utils.meta import read_meta_from_zip
from ..models import (
    BackupConflictError,
    BackupDetail,
    BackupMeta,
    DeleteBackupsResponse,
)
from ...constant import BACKUP_DIR

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# List
# ------------------------------------------------------------------


async def list_backups() -> list[BackupMeta]:
    return await asyncio.to_thread(_list_sync)


def _list_sync() -> list[BackupMeta]:
    if not BACKUP_DIR.is_dir():
        return []
    results: list[BackupMeta] = []
    for f in BACKUP_DIR.iterdir():
        if not (f.is_file() and f.suffix == ".zip"):
            continue
        try:
            with zipfile.ZipFile(f, "r") as zf:
                meta_json = read_meta_from_zip(zf)
                if meta_json is not None:
                    results.append(
                        BackupMeta.model_validate_json(meta_json),
                    )
        except Exception as exc:
            logger.warning(
                "Skipping invalid backup file: %s: %s: %s",
                f.name,
                type(exc).__name__,
                exc,
            )
    results.sort(key=lambda s: s.created_at, reverse=True)
    return results


# ------------------------------------------------------------------
# Detail
# ------------------------------------------------------------------


async def get_backup(backup_id: str) -> BackupDetail | None:
    return await asyncio.to_thread(_detail_sync, backup_id)


def _detail_sync(backup_id: str) -> BackupDetail | None:
    zp = zip_path(backup_id)
    if not zp.is_file():
        return None
    try:
        with zipfile.ZipFile(zp, "r") as zf:
            meta_json = read_meta_from_zip(zf)
            if meta_json is None:
                return None
            meta = BackupMeta.model_validate_json(meta_json)

            stats: dict[str, dict] = {}
            agent_json_paths: dict[str, str] = {}
            for info in zf.infolist():
                if (
                    info.filename.startswith(PREFIX_WORKSPACES)
                    and not info.is_dir()
                ):
                    parts = info.filename.split("/", 3)
                    if len(parts) >= 4:
                        aid = parts[2]
                        if aid not in stats:
                            stats[aid] = {"files": 0, "size": 0}
                        stats[aid]["files"] += 1
                        stats[aid]["size"] += info.file_size
                        # Remember each agent's agent.json path so we can
                        # extract the human-readable name below. The custom
                        # restore UI needs this for new (not-yet-existing)
                        # agents which can't be looked up via /api/agents.
                        if parts[3] == "agent.json":
                            agent_json_paths[aid] = info.filename

            for aid, json_path in agent_json_paths.items():
                try:
                    raw = zf.read(json_path)
                    data = json.loads(raw)
                    name = data.get("name")
                    if isinstance(name, str) and name:
                        stats[aid]["name"] = name
                except Exception as exc:
                    logger.debug(
                        "Failed to read agent name from %s"
                        " in backup %s: %s: %s",
                        json_path,
                        backup_id,
                        type(exc).__name__,
                        exc,
                    )
            return BackupDetail(**meta.model_dump(), workspace_stats=stats)
    except Exception as exc:
        logger.warning(
            "Failed to read backup: %s: %s: %s",
            backup_id,
            type(exc).__name__,
            exc,
        )
        return None


# ------------------------------------------------------------------
# Delete
# ------------------------------------------------------------------


async def delete_backups(ids: list[str]) -> DeleteBackupsResponse:
    return await asyncio.to_thread(_delete_sync, ids)


def _delete_sync(ids: list[str]) -> DeleteBackupsResponse:
    logger.info("Deleting %d backup(s): %s", len(ids), ids)
    resp = DeleteBackupsResponse()
    for sid in ids:
        zp = zip_path(sid)
        if not zp.is_file():
            logger.warning("Delete failed: backup not found: %s", sid)
            resp.failed.append({"id": sid, "reason": "not found"})
            continue
        try:
            zp.unlink()
            logger.info("Deleted backup: %s", sid)
            resp.deleted.append(sid)
        except Exception as exc:
            logger.error("Failed to delete backup %s: %s", sid, exc)
            resp.failed.append({"id": sid, "reason": str(exc)})
    return resp


# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------


async def export_backup(backup_id: str) -> tuple[Path, str]:
    """Return (zip_file_path, backup_name)."""
    return await asyncio.to_thread(_export_sync, backup_id)


def _export_sync(backup_id: str) -> tuple[Path, str]:
    zp = zip_path(backup_id)
    if not zp.is_file():
        raise FileNotFoundError(f"Backup not found: {backup_id}")

    with zipfile.ZipFile(zp, "r") as zf:
        meta_json = read_meta_from_zip(zf)
        if meta_json is None:
            raise FileNotFoundError(f"Backup not found: {backup_id}")
        meta = BackupMeta.model_validate_json(meta_json)
    return zp, meta.name


# ------------------------------------------------------------------
# Import
# ------------------------------------------------------------------


async def import_backup(
    tmp_path: Path,
    *,
    overwrite: bool = False,
) -> BackupMeta:
    """Import a backup from a temporary file on disk.

    When *overwrite* is ``False`` (default) and the backup's ID already exists
    on disk, :class:`BackupConflictError` is raised so the caller can surface
    the conflict to the user.  Pass ``overwrite=True`` to replace the existing
    backup without asking.

    The caller is responsible for cleaning up *tmp_path* afterwards.
    """
    return await asyncio.to_thread(_import_sync, tmp_path, overwrite)


def _import_sync(
    tmp_path: Path,
    overwrite: bool = False,
) -> BackupMeta:
    """Validate and store an uploaded backup zip from *tmp_path*."""
    logger.info(
        "Importing backup from %s (overwrite=%s)",
        tmp_path,
        overwrite,
    )
    if not zipfile.is_zipfile(tmp_path):
        raise ValueError("Uploaded file is not a valid zip archive")

    with zipfile.ZipFile(tmp_path, "r") as zf:
        meta_json = read_meta_from_zip(zf)
        if meta_json is None:
            raise ValueError("Zip does not contain a valid meta.json")
        meta = BackupMeta.model_validate_json(meta_json)

    validate_backup_id(meta.id)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    existing = zip_path(meta.id)

    if existing.is_file() and not overwrite:
        logger.warning(
            "Import conflict: backup id=%s already exists;"
            " raising BackupConflictError",
            meta.id,
        )
        raise BackupConflictError(meta)

    dest = zip_path(meta.id)
    # tmp_path lives in BACKUP_DIR (via mkstemp(dir=BACKUP_DIR)),
    # so this rename is within the same filesystem and is atomic.
    tmp_path.replace(dest)
    logger.info(
        "Backup imported: id=%s name=%r dest=%s",
        meta.id,
        meta.name,
        dest,
    )
    return meta

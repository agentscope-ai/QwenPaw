# -*- coding: utf-8 -*-
"""Backup & migration REST API.

Provides endpoints for asset export/import, backup listing,
restore, and backup configuration management.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from ...backup.exporter import AssetExporter, ExportOptions
from ...backup.importer import AssetImporter
from ...backup.models import AssetType, BackupConfig, ConflictStrategy
from ...backup.scheduler import BackupScheduler
from ...constant import WORKING_DIR

router = APIRouter(prefix="/backup", tags=["backup"])

_DEFAULT_BACKUP_DIR = Path.home() / ".copaw" / "backups"
_CONFIG_FILE = WORKING_DIR / "backup_config.json"

_VALID_TYPES = {t.value for t in AssetType}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_config() -> BackupConfig:
    if _CONFIG_FILE.is_file():
        try:
            data = json.loads(_CONFIG_FILE.read_text("utf-8"))
            return BackupConfig(
                enabled=data.get("enabled", False),
                schedule=data.get("schedule", "0 2 * * *"),
                retention_days=data.get("retention_days", 7),
                max_backups=data.get("max_backups", 30),
                include_types=[
                    AssetType(t)
                    for t in data.get(
                        "include_types",
                        [t.value for t in AssetType],
                    )
                    if t in _VALID_TYPES
                ],
            )
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return BackupConfig()


def _save_config(config: BackupConfig) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(
        json.dumps(
            {
                "enabled": config.enabled,
                "schedule": config.schedule,
                "retention_days": config.retention_days,
                "max_backups": config.max_backups,
                "include_types": [t.value for t in config.include_types],
            },
            indent=2,
            ensure_ascii=False,
        ),
        "utf-8",
    )


def _parse_types(types: Optional[list[str]]) -> Optional[list[AssetType]]:
    if types is None:
        return None
    result: list[AssetType] = []
    for t in types:
        if t not in _VALID_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid asset type: {t!r}. "
                f"Valid types: {sorted(_VALID_TYPES)}",
            )
        result.append(AssetType(t))
    return result or None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/export", summary="Export workspace assets")
async def export_assets(
    body: dict = Body(
        ...,
        description=(
            '{"workspace_dir": "...", "types": [...], "output_path": "..."}'
        ),
    ),
) -> dict:
    workspace_dir = Path(
        body.get("workspace_dir", str(WORKING_DIR)),
    ).expanduser()
    if not workspace_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Workspace directory not found: {workspace_dir}",
        )

    asset_types = _parse_types(body.get("types"))
    output_path = body.get("output_path")

    include_all = asset_types is None
    types_list = asset_types or []
    options = ExportOptions(
        workspace_dir=workspace_dir,
        include_preferences=include_all
        or AssetType.PREFERENCES in types_list,
        include_memories=include_all or AssetType.MEMORIES in types_list,
        include_skills=include_all or AssetType.SKILLS in types_list,
        include_tools=include_all or AssetType.TOOLS in types_list,
        include_global_config=include_all
        or AssetType.GLOBAL_CONFIG in types_list,
        output_path=Path(output_path).expanduser() if output_path else None,
    )

    try:
        exporter = AssetExporter()
        result = await exporter.export_assets(options)
        return {
            "zip_path": str(result.zip_path),
            "asset_count": result.asset_count,
            "total_size_bytes": result.total_size_bytes,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/import", summary="Import assets from ZIP")
async def import_assets(
    body: dict = Body(
        ...,
        description='{"zip_path": "...", "strategy": "...", "types": [...]}',
    ),
) -> dict:
    zip_path_str = body.get("zip_path")
    if not zip_path_str:
        raise HTTPException(status_code=400, detail="zip_path is required")
    zip_path = Path(zip_path_str).expanduser()
    if not zip_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"ZIP file not found: {zip_path}",
        )

    strategy_str = body.get("strategy", "ask")
    try:
        strategy = ConflictStrategy(strategy_str.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid strategy: {strategy_str!r}",
        )

    asset_types = _parse_types(body.get("types"))

    try:
        importer = AssetImporter(workspace_dir=WORKING_DIR)
        result = await importer.import_assets(
            zip_path=zip_path,
            strategy=strategy,
            asset_types=asset_types,
        )
        return {
            "imported": result.imported,
            "skipped": result.skipped,
            "conflicts_count": len(result.conflicts),
            "errors": result.errors,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/list", summary="List all backups")
async def list_backups() -> dict:
    scheduler = BackupScheduler()
    backups = await asyncio.to_thread(
        scheduler.list_backups,
        _DEFAULT_BACKUP_DIR,
    )
    return {
        "backups": [
            {
                "backup_path": str(b.backup_path),
                "timestamp": b.timestamp,
                "size_bytes": b.size_bytes,
                "asset_count": b.asset_count,
                "success": b.success,
            }
            for b in backups
        ],
    }


@router.post("/restore", summary="Restore from backup")
async def restore_backup(
    body: dict = Body(
        ...,
        description='{"backup_name": "...", "strategy": "overwrite"}',
    ),
) -> dict:
    backup_name = body.get("backup_name")
    if not backup_name:
        raise HTTPException(
            status_code=400,
            detail="backup_name is required",
        )

    strategy_str = body.get("strategy", "overwrite")
    try:
        strategy = ConflictStrategy(strategy_str.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid strategy: {strategy_str!r}",
        )

    scheduler = BackupScheduler()

    if backup_name == "latest":
        backups = await asyncio.to_thread(
            scheduler.list_backups,
            _DEFAULT_BACKUP_DIR,
        )
        if not backups:
            raise HTTPException(status_code=404, detail="No backups found")
        backup_path = backups[0].backup_path
    else:
        backup_path = _DEFAULT_BACKUP_DIR / backup_name
        if not backup_path.exists():
            backup_path = Path(backup_name).expanduser()

    if not backup_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Backup not found: {backup_path}",
        )

    try:
        result = await scheduler.restore_from_backup(
            backup_path=backup_path,
            workspace_dir=WORKING_DIR,
            strategy=strategy,
        )
        return {
            "imported": result.imported,
            "skipped": result.skipped,
            "conflicts_count": len(result.conflicts),
            "errors": result.errors,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/config", summary="Get backup configuration")
async def get_config() -> dict:
    config = _load_config()
    return {
        "enabled": config.enabled,
        "schedule": config.schedule,
        "retention_days": config.retention_days,
        "max_backups": config.max_backups,
        "include_types": [t.value for t in config.include_types],
    }


@router.put("/config", summary="Update backup configuration")
async def put_config(
    body: dict = Body(
        ...,
        description='{"enabled": true, "schedule": "0 2 * * *", ...}',
    ),
) -> dict:
    config = _load_config()

    if "enabled" in body:
        config.enabled = bool(body["enabled"])
    if "schedule" in body:
        config.schedule = str(body["schedule"])
    if "retention_days" in body:
        val = body["retention_days"]
        if not isinstance(val, int) or val < 1:
            raise HTTPException(
                status_code=400,
                detail="retention_days must be a positive integer",
            )
        config.retention_days = val
    if "max_backups" in body:
        val = body["max_backups"]
        if not isinstance(val, int) or val < 1:
            raise HTTPException(
                status_code=400,
                detail="max_backups must be a positive integer",
            )
        config.max_backups = val
    if "include_types" in body:
        parsed = _parse_types(body["include_types"])
        config.include_types = parsed or list(AssetType)

    _save_config(config)

    return {
        "enabled": config.enabled,
        "schedule": config.schedule,
        "retention_days": config.retention_days,
        "max_backups": config.max_backups,
        "include_types": [t.value for t in config.include_types],
    }

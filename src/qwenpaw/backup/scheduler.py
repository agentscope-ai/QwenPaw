# -*- coding: utf-8 -*-
"""Backup scheduler — manages backup creation, cleanup, listing and restore."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from qwenpaw.backup.exporter import AssetExporter
from qwenpaw.backup.importer import AssetImporter
from qwenpaw.backup.models import (
    BackupConfig,
    BackupResult,
    ConflictStrategy,
    ExportOptions,
    ImportResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BACKUP_FILENAME_RE = re.compile(
    r"^backup-(?P<agent_id>.+)-(?P<ts>\d{8}-\d{6})\.copaw-assets\.zip$",
)
_BACKUP_TS_FMT = "%Y%m%d-%H%M%S"
_DEFAULT_BACKUP_DIR = Path.home() / ".copaw" / "backups"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_agent_id(workspace_dir: Path) -> str:
    """Read agent id from workspace agent.json."""
    import json

    agent_json = workspace_dir / "agent.json"
    if agent_json.exists():
        try:
            data = json.loads(agent_json.read_text(encoding="utf-8"))
            return data.get("id", "unknown")
        except (json.JSONDecodeError, OSError):
            pass
    return "unknown"


def _parse_backup_filename(name: str) -> Optional[tuple[str, datetime]]:
    """Parse a backup filename and return (agent_id, timestamp) or None."""
    m = _BACKUP_FILENAME_RE.match(name)
    if not m:
        return None
    try:
        ts = datetime.strptime(m.group("ts"), _BACKUP_TS_FMT).replace(
            tzinfo=timezone.utc,
        )
        return m.group("agent_id"), ts
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# BackupScheduler
# ---------------------------------------------------------------------------


class BackupScheduler:
    """Manages backup creation, retention cleanup, listing and restore."""

    def __init__(
        self,
        config: Optional[BackupConfig] = None,
        exporter: Optional[AssetExporter] = None,
    ) -> None:
        self._config = config or BackupConfig()
        self._exporter = exporter or AssetExporter()

    # -- backup --------------------------------------------------------------

    async def run_backup(self, workspace_dir: Path) -> BackupResult:
        """Execute a full backup of the workspace.

        The backup ZIP is written to ``~/.copaw/backups/`` with the naming
        convention ``backup-{agent_id}-{YYYYMMDD-HHmmss}.copaw-assets.zip``.
        """
        now = datetime.now(timezone.utc)
        ts_str = now.strftime(_BACKUP_TS_FMT)
        agent_id = _get_agent_id(workspace_dir)

        backup_dir = _DEFAULT_BACKUP_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)

        filename = f"backup-{agent_id}-{ts_str}.copaw-assets.zip"
        output_path = backup_dir / filename

        try:
            result = await self._exporter.export_assets(
                ExportOptions(
                    workspace_dir=workspace_dir,
                    include_preferences=True,
                    include_memories=True,
                    include_skills=True,
                    include_tools=True,
                    output_path=output_path,
                ),
            )
            return BackupResult(
                backup_path=result.zip_path,
                timestamp=ts_str,
                size_bytes=result.total_size_bytes,
                asset_count=result.asset_count,
                success=True,
            )
        except Exception as exc:
            logger.error("Backup failed: %s", exc)
            return BackupResult(
                backup_path=output_path,
                timestamp=ts_str,
                size_bytes=0,
                asset_count=0,
                success=False,
                error=str(exc),
            )

    # -- cleanup -------------------------------------------------------------

    async def cleanup_old_backups(
        self,
        backup_dir: Path,
        config: Optional[BackupConfig] = None,
    ) -> int:
        """Remove old backups exceeding retention_days or max_backups.

        Returns the number of backup files removed.
        """
        cfg = config or self._config
        if not backup_dir.exists():
            return 0

        # Collect all valid backup files with their timestamps
        backups: list[tuple[Path, datetime]] = []
        for p in backup_dir.iterdir():
            if not p.is_file():
                continue
            parsed = _parse_backup_filename(p.name)
            if parsed is not None:
                _, ts = parsed
                backups.append((p, ts))

        # Sort by timestamp ascending (oldest first)
        backups.sort(key=lambda x: x[1])

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=cfg.retention_days)
        removed = 0

        # Phase 1: remove backups older than retention_days
        still_valid: list[tuple[Path, datetime]] = []
        for path, ts in backups:
            if ts < cutoff:
                try:
                    path.unlink()
                    removed += 1
                    logger.info("Removed expired backup: %s", path.name)
                except OSError as exc:
                    logger.warning(
                        "Failed to remove backup %s: %s",
                        path.name,
                        exc,
                    )
                    still_valid.append((path, ts))
            else:
                still_valid.append((path, ts))

        # Phase 2: enforce max_backups (remove oldest first)
        while len(still_valid) > cfg.max_backups:
            path, _ = still_valid.pop(0)
            try:
                path.unlink()
                removed += 1
                logger.info("Removed excess backup: %s", path.name)
            except OSError as exc:
                logger.warning(
                    "Failed to remove backup %s: %s",
                    path.name,
                    exc,
                )

        return removed

    # -- list ----------------------------------------------------------------

    def list_backups(self, backup_dir: Path) -> list[BackupResult]:
        """List all backup files in the given directory.

        Parses backup filenames to extract timestamp and agent_id.
        Returns a list of BackupResult sorted by timestamp descending
        (newest first).
        """
        if not backup_dir.exists():
            return []

        results: list[BackupResult] = []
        for p in backup_dir.iterdir():
            if not p.is_file():
                continue
            parsed = _parse_backup_filename(p.name)
            if parsed is None:
                continue
            _, ts = parsed
            try:
                size = p.stat().st_size
            except OSError:
                size = 0

            results.append(
                BackupResult(
                    backup_path=p,
                    timestamp=ts.strftime(_BACKUP_TS_FMT),
                    size_bytes=size,
                    asset_count=0,  # would need to read ZIP to know
                    success=True,
                ),
            )

        # Sort newest first
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results

    # -- restore -------------------------------------------------------------

    async def restore_from_backup(
        self,
        backup_path: Path,
        workspace_dir: Path,
        strategy: ConflictStrategy = ConflictStrategy.OVERWRITE,
    ) -> ImportResult:
        """Restore a workspace from a backup ZIP using AssetImporter."""
        importer = AssetImporter(workspace_dir=workspace_dir)
        return await importer.import_assets(
            zip_path=backup_path,
            strategy=strategy,
        )

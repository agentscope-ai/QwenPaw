# -*- coding: utf-8 -*-
"""Unit tests for BackupScheduler."""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from qwenpaw.backup.models import BackupConfig, ConflictStrategy
from qwenpaw.backup.scheduler import (
    BackupScheduler,
    _parse_backup_filename,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "agent.json").write_text(
        json.dumps({"id": "test-agent", "name": "Test"}),
        encoding="utf-8",
    )
    (ws / "config.json").write_text(
        json.dumps({"key": "value"}),
        encoding="utf-8",
    )
    return ws


def _create_fake_backup(backup_dir: Path, agent_id: str, ts: datetime) -> Path:
    """Create a minimal fake backup ZIP file."""
    ts_str = ts.strftime("%Y%m%d-%H%M%S")
    name = f"backup-{agent_id}-{ts_str}.copaw-assets.zip"
    path = backup_dir / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", "{}")
    return path


# ---------------------------------------------------------------------------
# Tests: filename parsing
# ---------------------------------------------------------------------------


def test_parse_backup_filename_valid() -> None:
    result = _parse_backup_filename(
        "backup-myagent-20250101-020000.copaw-assets.zip",
    )
    assert result is not None
    agent_id, ts = result
    assert agent_id == "myagent"
    assert ts.year == 2025
    assert ts.month == 1
    assert ts.day == 1


def test_parse_backup_filename_invalid() -> None:
    assert _parse_backup_filename("random-file.zip") is None
    assert _parse_backup_filename("backup-.zip") is None


# ---------------------------------------------------------------------------
# Tests: run_backup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_backup_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _create_workspace(tmp_path)
    backup_dir = tmp_path / "backups"

    # Monkeypatch the default backup dir
    monkeypatch.setattr(
        "qwenpaw.backup.scheduler._DEFAULT_BACKUP_DIR",
        backup_dir,
    )

    scheduler = BackupScheduler()
    result = await scheduler.run_backup(ws)

    assert result.success is True
    assert result.backup_path.exists()
    assert result.size_bytes > 0
    assert "backup-test-agent-" in result.backup_path.name
    assert result.backup_path.name.endswith(".copaw-assets.zip")


@pytest.mark.asyncio
async def test_run_backup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backup on nonexistent workspace returns success=False."""
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(
        "qwenpaw.backup.scheduler._DEFAULT_BACKUP_DIR",
        backup_dir,
    )

    scheduler = BackupScheduler()
    result = await scheduler.run_backup(tmp_path / "nonexistent")

    assert result.success is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Tests: cleanup_old_backups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_removes_expired(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    now = datetime.now(timezone.utc)
    # Create an old backup (10 days ago) and a recent one
    _create_fake_backup(backup_dir, "agent", now - timedelta(days=10))
    _create_fake_backup(backup_dir, "agent", now - timedelta(seconds=60))

    config = BackupConfig(retention_days=7, max_backups=100)
    scheduler = BackupScheduler(config=config)
    removed = await scheduler.cleanup_old_backups(backup_dir, config)

    assert removed == 1
    remaining = list(backup_dir.glob("backup-*.copaw-assets.zip"))
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_cleanup_enforces_max_backups(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    now = datetime.now(timezone.utc)
    # Create 5 recent backups, max_backups=3
    for i in range(5):
        _create_fake_backup(backup_dir, "agent", now - timedelta(minutes=i))

    config = BackupConfig(retention_days=365, max_backups=3)
    scheduler = BackupScheduler(config=config)
    removed = await scheduler.cleanup_old_backups(backup_dir, config)

    assert removed == 2
    remaining = list(backup_dir.glob("backup-*.copaw-assets.zip"))
    assert len(remaining) == 3


@pytest.mark.asyncio
async def test_cleanup_nonexistent_dir(tmp_path: Path) -> None:
    scheduler = BackupScheduler()
    removed = await scheduler.cleanup_old_backups(tmp_path / "nope")
    assert removed == 0


# ---------------------------------------------------------------------------
# Tests: list_backups
# ---------------------------------------------------------------------------


def test_list_backups(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    now = datetime.now(timezone.utc)
    _create_fake_backup(backup_dir, "agent", now - timedelta(days=1))
    _create_fake_backup(backup_dir, "agent", now)

    scheduler = BackupScheduler()
    results = scheduler.list_backups(backup_dir)

    assert len(results) == 2
    # Newest first
    assert results[0].timestamp >= results[1].timestamp


def test_list_backups_empty(tmp_path: Path) -> None:
    scheduler = BackupScheduler()
    assert not scheduler.list_backups(tmp_path / "nope")


# ---------------------------------------------------------------------------
# Tests: restore_from_backup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_from_backup(tmp_path: Path) -> None:
    """Create a real backup then restore it to a new workspace."""
    ws = _create_workspace(tmp_path)
    output = tmp_path / "backup.zip"

    from qwenpaw.backup.exporter import AssetExporter
    from qwenpaw.backup.models import ExportOptions

    exporter = AssetExporter()
    await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=output,
        ),
    )

    # Restore to a new workspace
    target_ws = tmp_path / "target"
    target_ws.mkdir()

    scheduler = BackupScheduler()
    import_result = await scheduler.restore_from_backup(
        backup_path=output,
        workspace_dir=target_ws,
        strategy=ConflictStrategy.OVERWRITE,
    )

    assert len(import_result.imported) > 0
    assert len(import_result.errors) == 0

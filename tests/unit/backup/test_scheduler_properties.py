# -*- coding: utf-8 -*-
"""Property-based tests for backup retention policy.

**Property 7: 备份保留策略**
**Validates: Requirements 6.1, 6.2**
"""
from __future__ import annotations

import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qwenpaw.backup.models import BackupConfig
from qwenpaw.backup.scheduler import BackupScheduler, _parse_backup_filename

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Reasonable retention config values
_retention_days = st.integers(min_value=1, max_value=365)
_max_backups = st.integers(min_value=1, max_value=50)

# Number of backups to create (keep small for speed)
_num_backups = st.integers(min_value=0, max_value=20)

# Age of each backup in days (0 = today, up to 400 days old)
_backup_age_days = st.integers(min_value=0, max_value=400)


@st.composite
def _backup_scenario(draw: st.DrawFn) -> tuple[int, int, list[int]]:
    """Generate (retention_days, max_backups, list_of_backup_ages_in_days)."""
    ret_days = draw(_retention_days)
    max_b = draw(_max_backups)
    n = draw(_num_backups)
    ages = [draw(_backup_age_days) for _ in range(n)]
    return ret_days, max_b, ages


def _create_fake_backup(backup_dir: Path, agent_id: str, ts: datetime) -> Path:
    """Create a minimal fake backup ZIP file with the correct naming."""
    ts_str = ts.strftime("%Y%m%d-%H%M%S")
    name = f"backup-{agent_id}-{ts_str}.copaw-assets.zip"
    path = backup_dir / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", "{}")
    return path


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(scenario=_backup_scenario())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_cleanup_respects_max_backups(
    tmp_path_factory: pytest.TempPathFactory,
    scenario: tuple[int, int, list[int]],
) -> None:
    """After cleanup_old_backups: backup count ≤ max_backups.

    **Validates: Requirements 6.1**
    """
    retention_days, max_backups, ages = scenario
    backup_dir = tmp_path_factory.mktemp("backups")

    now = datetime.now(timezone.utc)
    for i, age in enumerate(ages):
        ts = now - timedelta(
            days=age,
            seconds=i,
        )  # seconds offset for uniqueness
        _create_fake_backup(backup_dir, "agent", ts)

    config = BackupConfig(
        retention_days=retention_days,
        max_backups=max_backups,
    )
    scheduler = BackupScheduler(config=config)
    await scheduler.cleanup_old_backups(backup_dir, config)

    remaining = [
        p
        for p in backup_dir.iterdir()
        if p.is_file() and _parse_backup_filename(p.name) is not None
    ]
    assert (
        len(remaining) <= max_backups
    ), f"Expected ≤ {max_backups} backups, found {len(remaining)}"


@given(scenario=_backup_scenario())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_cleanup_respects_retention_days(
    tmp_path_factory: pytest.TempPathFactory,
    scenario: tuple[int, int, list[int]],
) -> None:
    """After cleanup_old_backups: all remaining backups
    created within retention_days.

    **Validates: Requirements 6.2**
    """
    retention_days, max_backups, ages = scenario
    backup_dir = tmp_path_factory.mktemp("backups")

    now = datetime.now(timezone.utc)
    for i, age in enumerate(ages):
        ts = now - timedelta(days=age, seconds=i)
        _create_fake_backup(backup_dir, "agent", ts)

    config = BackupConfig(
        retention_days=retention_days,
        max_backups=max_backups,
    )
    scheduler = BackupScheduler(config=config)
    await scheduler.cleanup_old_backups(backup_dir, config)

    cutoff = now - timedelta(days=retention_days)
    for p in backup_dir.iterdir():
        if not p.is_file():
            continue
        parsed = _parse_backup_filename(p.name)
        if parsed is None:
            continue
        _, ts = parsed
        assert ts >= cutoff, (
            f"Backup {p.name} has timestamp {ts} which is older than "
            f"cutoff {cutoff} (retention_days={retention_days})"
        )

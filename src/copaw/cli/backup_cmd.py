# -*- coding: utf-8 -*-
"""CLI commands for backup management: ``copaw backup list|restore``."""
from __future__ import annotations

import asyncio
from pathlib import Path

import click

from ..backup.models import ConflictStrategy
from ..config import load_config
from ..constant import WORKING_DIR


_DEFAULT_BACKUP_DIR = Path.home() / ".copaw" / "backups"


def _get_workspace_dir(agent_id: str = "default") -> Path:
    """Resolve workspace directory for the given agent."""
    try:
        config = load_config()
        if agent_id in config.agents.profiles:
            ref = config.agents.profiles[agent_id]
            return Path(ref.workspace_dir).expanduser()
    except Exception:
        pass
    return WORKING_DIR


def _get_all_agent_ids() -> list[str]:
    """Return all configured agent IDs."""
    try:
        config = load_config()
        return list(config.agents.profiles.keys())
    except Exception:
        return ["default"]


@click.group("backup")
def backup_group() -> None:
    """Manage workspace backups."""


@backup_group.command("list")
@click.option(
    "--backup-dir",
    type=click.Path(),
    default=None,
    help=f"Backup directory (default: {_DEFAULT_BACKUP_DIR}).",
)
def list_cmd(backup_dir: str | None) -> None:
    """List all available backups."""
    from ..backup.scheduler import BackupScheduler

    bdir = Path(backup_dir).expanduser() if backup_dir else _DEFAULT_BACKUP_DIR

    scheduler = BackupScheduler()
    backups = scheduler.list_backups(bdir)

    if not backups:
        click.echo("No backups found.")
        return

    click.echo(f"\n{'─' * 70}")
    click.echo(f"  {'Timestamp':<22s} {'Size':>12s}  {'Path'}")
    click.echo(f"{'─' * 70}")

    for b in backups:
        size_str = _format_size(b.size_bytes)
        click.echo(
            f"  {b.timestamp:<22s} {size_str:>12s}  {b.backup_path.name}",
        )

    click.echo(f"{'─' * 70}")
    click.echo(f"  Total: {len(backups)} backup(s)\n")


@backup_group.command("run")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default').",
)
@click.option(
    "--all",
    "backup_all",
    is_flag=True,
    default=False,
    help="Backup all agents.",
)
def run_cmd(agent_id: str, backup_all: bool) -> None:
    """Run a backup now."""
    from ..backup.scheduler import BackupScheduler

    agent_ids = _get_all_agent_ids() if backup_all else [agent_id]
    scheduler = BackupScheduler()
    success_count = 0

    for aid in agent_ids:
        workspace_dir = _get_workspace_dir(aid)
        click.echo(f"Backing up agent '{aid}': {workspace_dir}")

        result = asyncio.run(scheduler.run_backup(workspace_dir))
        if result.success:
            click.echo(
                click.style(
                    f"  ✓ {result.asset_count} assets, "
                    f"{_format_size(result.size_bytes)}"
                    f" → {result.backup_path.name}",
                    fg="green",
                ),
            )
            success_count += 1
        else:
            click.echo(
                click.style(
                    f"  ✗ Failed: {result.error}",
                    fg="red",
                ),
                err=True,
            )

    if backup_all:
        click.echo(
            click.style(
                f"\n✓ Backed up {success_count}/{len(agent_ids)} agent(s)",
                fg="green",
            ),
        )


@backup_group.command("restore")
@click.argument("backup_name")
@click.option(
    "--strategy",
    "-s",
    type=click.Choice(
        ["skip", "overwrite", "rename", "ask"],
        case_sensitive=False,
    ),
    default="overwrite",
    help="Conflict resolution strategy (default: overwrite).",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default').",
)
@click.option(
    "--backup-dir",
    type=click.Path(),
    default=None,
    help=f"Backup directory (default: {_DEFAULT_BACKUP_DIR}).",
)
def restore_cmd(
    backup_name: str,
    strategy: str,
    agent_id: str,
    backup_dir: str | None,
) -> None:
    """Restore workspace from a backup.

    BACKUP_NAME can be 'latest' or a specific backup filename.
    """
    from ..backup.scheduler import BackupScheduler

    workspace_dir = _get_workspace_dir(agent_id)
    bdir = Path(backup_dir).expanduser() if backup_dir else _DEFAULT_BACKUP_DIR
    conflict_strategy = ConflictStrategy(strategy.lower())

    scheduler = BackupScheduler()

    # Resolve backup path
    if backup_name == "latest":
        backups = scheduler.list_backups(bdir)
        if not backups:
            click.echo(click.style("No backups found.", fg="red"), err=True)
            raise SystemExit(1)
        backup_path = backups[0].backup_path  # list is sorted newest first
    else:
        backup_path = bdir / backup_name
        if not backup_path.exists():
            # Try as absolute/relative path
            backup_path = Path(backup_name).expanduser()

    if not backup_path.exists():
        click.echo(
            click.style(f"Backup not found: {backup_path}", fg="red"),
            err=True,
        )
        raise SystemExit(1)

    click.echo(f"Restoring from: {backup_path.name}")
    click.echo(f"  Target workspace: {workspace_dir}")
    click.echo(f"  Strategy: {conflict_strategy.value}")

    try:
        result = asyncio.run(
            scheduler.restore_from_backup(
                backup_path=backup_path,
                workspace_dir=workspace_dir,
                strategy=conflict_strategy,
            ),
        )
        click.echo(
            click.style(
                f"\n✓ Restore complete: {len(result.imported)} imported, "
                f"{len(result.skipped)} skipped, "
                f"{len(result.conflicts)} conflicts",
                fg="green",
            ),
        )
        if result.errors:
            for err in result.errors:
                click.echo(click.style(f"  ⚠ {err}", fg="yellow"))
    except Exception as exc:
        click.echo(
            click.style(f"\n✗ Restore failed: {exc}", fg="red"),
            err=True,
        )
        raise SystemExit(1) from exc


def _format_size(size_bytes: int) -> str:
    """Format byte size into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

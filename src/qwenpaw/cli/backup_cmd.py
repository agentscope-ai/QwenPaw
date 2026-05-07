# -*- coding: utf-8 -*-
"""Backup management CLI commands."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, TypeVar

import click

from ..backup import (
    create_stream,
    delete_backups,
    execute_restore,
    export_backup,
    get_backup,
    import_backup,
    list_backups,
)
from ..backup.models import (
    BackupConflictError,
    BackupMeta,
    BackupScope,
    CreateBackupRequest,
    RestoreBackupRequest,
)
from ..config.utils import load_config
from ..constant import BACKUP_DIR
from .http import print_json

_T = TypeVar("_T")
_DURATION_RE = re.compile(r"^(?P<count>\d+)(?P<unit>[smhdw]?)$")


def _run(awaitable: Awaitable[_T]) -> _T:
    return asyncio.run(awaitable)


def _default_backup_name() -> str:
    return "Backup " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _model_dump(model) -> dict:
    return model.model_dump(mode="json")


def _ordered_agent_ids() -> list[str]:
    config = load_config()
    profiles = dict(config.agents.profiles)
    ordered = [
        aid
        for aid in getattr(config.agents, "agent_order", [])
        if aid in profiles
    ]
    ordered.extend(aid for aid in profiles if aid not in set(ordered))
    return ordered


def _resolve_create_agents(
    agent_ids: tuple[str, ...],
    *,
    full: bool,
) -> list[str]:
    available = _ordered_agent_ids()
    if full and agent_ids:
        raise click.ClickException("--full cannot be combined with --agent.")
    if not agent_ids:
        return available

    missing = [aid for aid in agent_ids if aid not in set(available)]
    if missing:
        raise click.ClickException(
            "Unknown agent id(s): " + ", ".join(sorted(missing)),
        )
    return list(dict.fromkeys(agent_ids))


def _duration(value: str) -> timedelta:
    match = _DURATION_RE.match(value.strip().lower())
    if match is None:
        raise click.BadParameter(
            "use an integer with optional suffix s, m, h, d, or w",
        )
    count = int(match.group("count"))
    unit = match.group("unit") or "d"
    if unit == "s":
        return timedelta(seconds=count)
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    if unit == "d":
        return timedelta(days=count)
    return timedelta(weeks=count)


def _created_at_utc(meta: BackupMeta) -> datetime:
    created_at = meta.created_at
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc)


def _select_prune_candidates(
    backups: list[BackupMeta],
    *,
    keep_last: int | None,
    older_than: str | None,
) -> list[BackupMeta]:
    cutoff = (
        datetime.now(timezone.utc) - _duration(older_than)
        if older_than
        else None
    )
    protected_ids = {
        meta.id for meta in backups[:keep_last]
    } if keep_last is not None else set()

    candidates: list[BackupMeta] = []
    for meta in backups:
        if meta.id in protected_ids:
            continue
        if cutoff is not None and _created_at_utc(meta) >= cutoff:
            continue
        candidates.append(meta)
    return candidates


def _print_backup_list(backups: list[BackupMeta]) -> None:
    print_json([_model_dump(meta) for meta in backups])


@click.group("backup")
def backup_group() -> None:
    """Manage local backups."""


@backup_group.command("list")
def list_cmd() -> None:
    """List local backups."""
    _print_backup_list(_run(list_backups()))


@backup_group.command("create")
@click.option("--name", default=None, help="Human-readable backup name.")
@click.option("--description", default="", help="Optional backup description.")
@click.option(
    "--full",
    is_flag=True,
    help="Back up all agents and all supported scopes, including secrets.",
)
@click.option(
    "--agent",
    "agent_ids",
    multiple=True,
    help="Agent ID to include. Repeat to include multiple agents.",
)
@click.option(
    "--include-secrets",
    is_flag=True,
    help="Include the secrets directory in a non-full backup.",
)
def create_cmd(
    name: str | None,
    description: str,
    full: bool,
    agent_ids: tuple[str, ...],
    include_secrets: bool,
) -> None:
    """Create a backup."""
    agents = _resolve_create_agents(agent_ids, full=full)
    scope = BackupScope(
        include_agents=full or bool(agents),
        include_global_config=True,
        include_secrets=full or include_secrets,
        include_skill_pool=True,
    )
    req = CreateBackupRequest(
        name=name or _default_backup_name(),
        description=description,
        scope=scope,
        agents=agents,
    )

    async def _create() -> dict:
        async for event in create_stream(req):
            event_type = event.get("type")
            if event_type == "error":
                raise click.ClickException(str(event.get("message", "")))
            if event_type == "agent":
                click.echo(
                    "backing up "
                    f"{event.get('agent_id')} "
                    f"({event.get('index')}/{event.get('total')})",
                    err=True,
                )
            if event_type == "done":
                meta = event.get("meta")
                if isinstance(meta, dict):
                    return meta
        raise click.ClickException("Backup creation did not finish.")

    print_json(_run(_create()))


@backup_group.command("restore")
@click.argument("backup_id")
@click.option("--full", "full_mode", is_flag=True, help="Run a full restore.")
@click.option(
    "--custom",
    "custom_mode",
    is_flag=True,
    help="Run a custom restore. This is the default.",
)
@click.option(
    "--agent",
    "agent_ids",
    multiple=True,
    help="Agent ID to restore in custom mode. Repeat for multiple agents.",
)
@click.option(
    "--include-secrets",
    is_flag=True,
    help="Include secrets during a custom restore.",
)
@click.option(
    "--default-workspace-dir",
    default=None,
    help="Base directory for newly restored agents.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the restore request without changing files.",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def restore_cmd(
    backup_id: str,
    full_mode: bool,
    custom_mode: bool,
    agent_ids: tuple[str, ...],
    include_secrets: bool,
    default_workspace_dir: str | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """Restore a backup."""
    if full_mode and custom_mode:
        raise click.ClickException("Use only one of --full or --custom.")

    detail = _run(get_backup(backup_id))
    if detail is None:
        raise click.ClickException(f"Backup not found: {backup_id}")

    backup_agent_ids = list(detail.workspace_stats.keys())
    if full_mode:
        mode = "full"
        selected_agents = backup_agent_ids
        req = RestoreBackupRequest(
            mode=mode,
            include_agents=True,
            agent_ids=selected_agents,
            include_global_config=True,
            include_secrets=True,
            include_skill_pool=True,
            default_workspace_dir=default_workspace_dir,
        )
    else:
        mode = "custom"
        selected_agents = (
            list(dict.fromkeys(agent_ids)) if agent_ids else backup_agent_ids
        )
        missing = [
            aid for aid in selected_agents if aid not in backup_agent_ids
        ]
        if missing:
            raise click.ClickException(
                "Agent id(s) not found in backup: "
                + ", ".join(sorted(missing)),
            )
        req = RestoreBackupRequest(
            mode=mode,
            include_agents=bool(selected_agents),
            agent_ids=selected_agents,
            include_global_config=detail.scope.include_global_config,
            include_secrets=include_secrets,
            include_skill_pool=detail.scope.include_skill_pool,
            default_workspace_dir=default_workspace_dir,
        )

    plan = {
        "backup_id": backup_id,
        "mode": mode,
        "request": req.model_dump(mode="json"),
    }
    if dry_run:
        print_json({"dry_run": True, **plan})
        return

    if not yes:
        click.echo(f"WARNING: You are about to restore backup '{backup_id}'.")
        click.echo("WARNING: This will modify local QwenPaw data.")
        click.confirm("Continue with restore?", abort=True)

    try:
        _run(execute_restore(backup_id, req))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    print_json({"ok": True, **plan})


@backup_group.command("export")
@click.argument("backup_id")
@click.option(
    "--output",
    "-o",
    required=True,
    type=click.Path(path_type=Path, dir_okay=False),
    help="Destination zip path.",
)
def export_cmd(backup_id: str, output: Path) -> None:
    """Export a backup zip."""
    if output.exists():
        raise click.ClickException(f"Output already exists: {output}")
    try:
        src, backup_name = _run(export_backup(backup_id))
    except FileNotFoundError as exc:
        raise click.ClickException(f"Backup not found: {backup_id}") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, output)
    print_json(
        {"id": backup_id, "name": backup_name, "path": str(output.resolve())},
    )


@backup_group.command("import")
@click.argument("path", type=click.Path(path_type=Path, dir_okay=False))
@click.option(
    "--overwrite",
    is_flag=True,
    help="Replace an existing backup with the same ID.",
)
def import_cmd(path: Path, overwrite: bool) -> None:
    """Import a backup zip."""
    if not path.is_file():
        raise click.ClickException(f"File not found: {path}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=BACKUP_DIR, suffix=".upload_tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as dst, open(path, "rb") as src:
            shutil.copyfileobj(src, dst)
        meta = _run(import_backup(tmp_path, overwrite=overwrite))
    except BackupConflictError as exc:
        raise click.ClickException(
            f"Backup '{exc.existing_meta.id}' already exists. "
            "Re-run with --overwrite to replace it.",
        ) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except OSError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    print_json(_model_dump(meta))


@backup_group.command("prune")
@click.option(
    "--keep-last",
    type=click.IntRange(min=0),
    default=None,
    help="Keep the newest N backups.",
)
@click.option(
    "--older-than",
    default=None,
    help="Delete backups older than this age, e.g. 30d, 12h, 2w.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="List matching backups without deleting them.",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def prune_cmd(
    keep_last: int | None,
    older_than: str | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """Delete old backups by age and/or retention count."""
    if keep_last is None and older_than is None:
        raise click.UsageError("Specify --keep-last, --older-than, or both.")

    backups = _run(list_backups())
    candidates = _select_prune_candidates(
        backups,
        keep_last=keep_last,
        older_than=older_than,
    )
    ids = [meta.id for meta in candidates]
    base_result = {
        "dry_run": dry_run,
        "matched": [_model_dump(meta) for meta in candidates],
    }
    if dry_run or not ids:
        print_json({**base_result, "deleted": [], "failed": []})
        return

    if not yes:
        click.echo(f"WARNING: {len(ids)} backup(s) will be deleted.")
        click.confirm("Continue with deletion?", abort=True)

    result = _run(delete_backups(ids))
    print_json({**base_result, **_model_dump(result)})


@backup_group.command("delete")
@click.argument("backup_ids", nargs=-1, required=True)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def delete_cmd(backup_ids: tuple[str, ...], yes: bool) -> None:
    """Delete one or more backups."""
    ids = list(dict.fromkeys(backup_ids))
    if not yes:
        click.echo(f"WARNING: {len(ids)} backup(s) will be deleted.")
        click.confirm("Continue with deletion?", abort=True)

    result = _run(delete_backups(ids))
    print_json(_model_dump(result))

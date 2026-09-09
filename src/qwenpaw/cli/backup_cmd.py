# -*- coding: utf-8 -*-
"""Backup management CLI commands."""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import click
import httpx

from .http import client, print_json, resolve_base_url

_DURATION_RE = re.compile(r"^(?P<count>\d+)(?P<unit>[smhdw]?)$")
_BACKEND_UNAVAILABLE = (
    "QwenPaw backend is not reachable. Start it with: qwenpaw app"
)
_base_url_option = click.option(
    "--base-url",
    default=None,
    help="Override API base URL, e.g. http://127.0.0.1:8088",
)


def _default_backup_name() -> str:
    return "Backup " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def _api_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text or response.reason_phrase

    detail = data.get("detail") if isinstance(data, dict) else data
    if isinstance(detail, str):
        return detail
    return json.dumps(detail, ensure_ascii=False)


def _raise_api_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    raise click.ClickException(_api_detail(response))


def _handle_request_error(exc: httpx.RequestError) -> click.ClickException:
    return click.ClickException(f"{_BACKEND_UNAVAILABLE} ({exc})")


def _backup_client(base_url: str) -> httpx.Client:
    api_client = client(base_url)
    # Backups can legitimately take longer than the generic CLI timeout.
    api_client.timeout = httpx.Timeout(None)
    return api_client


@contextmanager
def _open_backup_client(
    ctx: click.Context,
    base_url: Optional[str],
) -> Iterator[httpx.Client]:
    resolved_base_url = resolve_base_url(ctx, base_url)
    try:
        with _backup_client(resolved_base_url) as api_client:
            yield api_client
    except httpx.RequestError as exc:
        raise _handle_request_error(exc) from exc


def _json_response(response: httpx.Response) -> Any:
    _raise_api_error(response)
    return response.json()


def _agent_ids(payload: dict[str, Any]) -> list[str]:
    agents = payload.get("agents", [])
    if not isinstance(agents, list):
        return []
    return [
        agent["id"]
        for agent in agents
        if isinstance(agent, dict) and isinstance(agent.get("id"), str)
    ]


def _list_agent_ids(api_client: httpx.Client) -> list[str]:
    return _agent_ids(_json_response(api_client.get("/agents")))


def _resolve_create_agents(
    api_client: httpx.Client,
    agent_ids: tuple[str, ...],
    *,
    full: bool,
) -> list[str]:
    available = _list_agent_ids(api_client)
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


def _load_backup_detail(
    api_client: httpx.Client,
    backup_id: str,
) -> dict[str, Any]:
    response = api_client.get(f"/backups/{backup_id}")
    if response.status_code == 404:
        raise click.ClickException(f"Backup not found: {backup_id}")
    return _json_response(response)


def _backup_agent_ids(detail: dict[str, Any]) -> list[str]:
    workspace_stats = detail.get("workspace_stats", {})
    if isinstance(workspace_stats, dict):
        return list(workspace_stats)
    return []


def _scope(detail: dict[str, Any]) -> dict[str, Any]:
    scope = detail.get("scope", {})
    return scope if isinstance(scope, dict) else {}


def _parse_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        created_at = value
    elif isinstance(value, str):
        created_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        created_at = datetime.min.replace(tzinfo=timezone.utc)

    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc)


def _sort_backups(backups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        backups,
        key=lambda item: _parse_created_at(item.get("created_at")),
        reverse=True,
    )


def _select_prune_candidates(
    backups: list[dict[str, Any]],
    *,
    keep_last: int | None,
    older_than: str | None,
) -> list[dict[str, Any]]:
    ordered = _sort_backups(backups)
    cutoff = (
        datetime.now(timezone.utc) - _duration(older_than)
        if older_than
        else None
    )
    protected_ids = {
        meta.get("id") for meta in ordered[:keep_last]
    } if keep_last is not None else set()

    candidates: list[dict[str, Any]] = []
    for meta in ordered:
        if meta.get("id") in protected_ids:
            continue
        if cutoff is not None:
            try:
                if _parse_created_at(meta.get("created_at")) >= cutoff:
                    continue
            except ValueError as exc:
                raise click.ClickException(
                    f"Invalid created_at in backup {meta.get('id')}: {exc}",
                ) from exc
        candidates.append(meta)
    return candidates


def _iter_sse_events(response: httpx.Response) -> Iterable[dict[str, Any]]:
    for line in response.iter_lines():
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise click.ClickException(
                f"Invalid backup stream event: {payload}",
            ) from exc
        if isinstance(event, dict):
            yield event


def _read_create_result(response: httpx.Response) -> dict[str, Any]:
    for event in _iter_sse_events(response):
        event_type = event.get("type")
        if event_type == "error":
            raise click.ClickException(str(event.get("message", "")))
        if event_type == "done":
            meta = event.get("meta")
            if isinstance(meta, dict):
                return meta
            raise click.ClickException("Backup creation returned no metadata.")
    raise click.ClickException("Backup creation did not finish.")


def _build_restore_request(
    detail: dict[str, Any],
    *,
    full_mode: bool,
    agent_ids: tuple[str, ...],
    include_secrets: bool,
    default_workspace_dir: str | None,
) -> tuple[str, dict[str, Any]]:
    backup_agent_ids = _backup_agent_ids(detail)
    if full_mode:
        return "full", {
            "mode": "full",
            "include_agents": True,
            "agent_ids": backup_agent_ids,
            "include_global_config": True,
            "include_secrets": True,
            "include_skill_pool": True,
            "default_workspace_dir": default_workspace_dir,
        }

    selected_agents = (
        list(dict.fromkeys(agent_ids)) if agent_ids else backup_agent_ids
    )
    missing = [aid for aid in selected_agents if aid not in backup_agent_ids]
    if missing:
        raise click.ClickException(
            "Agent id(s) not found in backup: "
            + ", ".join(sorted(missing)),
        )

    scope = _scope(detail)
    return "custom", {
        "mode": "custom",
        "include_agents": bool(selected_agents),
        "agent_ids": selected_agents,
        "include_global_config": bool(
            scope.get("include_global_config", True),
        ),
        "include_secrets": include_secrets,
        "include_skill_pool": bool(scope.get("include_skill_pool", True)),
        "default_workspace_dir": default_workspace_dir,
    }


def _confirm_delete(count: int) -> None:
    click.echo(f"WARNING: {count} backup(s) will be deleted.")
    click.confirm("Continue with deletion?", abort=True)


def _delete_backups(
    api_client: httpx.Client,
    ids: list[str],
) -> dict[str, Any]:
    return _json_response(api_client.post("/backups/delete", json={"ids": ids}))


@click.group("backup")
def backup_group() -> None:
    """Manage backups via the QwenPaw backend."""


@backup_group.command("list")
@_base_url_option
@click.pass_context
def list_cmd(ctx: click.Context, base_url: Optional[str]) -> None:
    """List backups."""
    with _open_backup_client(ctx, base_url) as api_client:
        print_json(_json_response(api_client.get("/backups")))


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
@_base_url_option
@click.pass_context
def create_cmd(
    ctx: click.Context,
    name: str | None,
    description: str,
    full: bool,
    agent_ids: tuple[str, ...],
    include_secrets: bool,
    base_url: Optional[str],
) -> None:
    """Create a backup."""
    with _open_backup_client(ctx, base_url) as api_client:
        agents = _resolve_create_agents(api_client, agent_ids, full=full)
        payload = {
            "name": name or _default_backup_name(),
            "description": description,
            "scope": {
                "include_agents": full or bool(agents),
                "include_global_config": True,
                "include_secrets": full or include_secrets,
                "include_skill_pool": True,
            },
            "agents": agents,
        }
        with api_client.stream(
            "POST",
            "/backups/stream",
            json=payload,
        ) as response:
            _raise_api_error(response)
            print_json(_read_create_result(response))


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
@_base_url_option
@click.pass_context
def restore_cmd(
    ctx: click.Context,
    backup_id: str,
    full_mode: bool,
    custom_mode: bool,
    agent_ids: tuple[str, ...],
    include_secrets: bool,
    default_workspace_dir: str | None,
    dry_run: bool,
    yes: bool,
    base_url: Optional[str],
) -> None:
    """Restore a backup."""
    if full_mode and custom_mode:
        raise click.ClickException("Use only one of --full or --custom.")

    with _open_backup_client(ctx, base_url) as api_client:
        detail = _load_backup_detail(api_client, backup_id)
        mode, request = _build_restore_request(
            detail,
            full_mode=full_mode,
            agent_ids=agent_ids,
            include_secrets=include_secrets,
            default_workspace_dir=default_workspace_dir,
        )
        plan = {"backup_id": backup_id, "mode": mode, "request": request}
        if dry_run:
            print_json({"dry_run": True, **plan})
            return

        if not yes:
            click.echo(
                f"WARNING: You are about to restore backup '{backup_id}'.",
            )
            click.echo("WARNING: This will modify local QwenPaw data.")
            click.confirm("Continue with restore?", abort=True)

        response = api_client.post(
            f"/backups/{backup_id}/restore",
            json=request,
        )
        _raise_api_error(response)
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
@_base_url_option
@click.pass_context
def export_cmd(
    ctx: click.Context,
    backup_id: str,
    output: Path,
    base_url: Optional[str],
) -> None:
    """Export a backup zip."""
    if output.exists():
        raise click.ClickException(f"Output already exists: {output}")

    with _open_backup_client(ctx, base_url) as api_client:
        response = api_client.get(f"/backups/{backup_id}/export")
        if response.status_code == 404:
            raise click.ClickException(f"Backup not found: {backup_id}")
        _raise_api_error(response)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(response.content)
        print_json({"id": backup_id, "path": str(output.resolve())})


@backup_group.command("import")
@click.argument("path", type=click.Path(path_type=Path, dir_okay=False))
@click.option(
    "--overwrite",
    is_flag=True,
    help="Replace an existing backup with the same ID.",
)
@_base_url_option
@click.pass_context
def import_cmd(
    ctx: click.Context,
    path: Path,
    overwrite: bool,
    base_url: Optional[str],
) -> None:
    """Import a backup zip."""
    if not path.is_file():
        raise click.ClickException(f"File not found: {path}")

    with _open_backup_client(ctx, base_url) as api_client:
        with path.open("rb") as file:
            response = api_client.post(
                "/backups/import",
                files={"file": (path.name, file, "application/zip")},
            )
        if response.status_code == 409:
            conflict = response.json()
            if not overwrite:
                existing = conflict.get("existing", {})
                backup_id = existing.get("id", "unknown")
                raise click.ClickException(
                    f"Backup '{backup_id}' already exists. "
                    "Re-run with --overwrite to replace it.",
                )
            pending_token = conflict.get("pending_token")
            if not pending_token:
                raise click.ClickException(
                    "Import conflict response did not include pending_token.",
                )
            response = api_client.post(
                "/backups/import",
                data={"pending_token": pending_token},
            )

        print_json(_json_response(response))


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
@_base_url_option
@click.pass_context
def prune_cmd(
    ctx: click.Context,
    keep_last: int | None,
    older_than: str | None,
    dry_run: bool,
    yes: bool,
    base_url: Optional[str],
) -> None:
    """Delete old backups by age and/or retention count."""
    if keep_last is None and older_than is None:
        raise click.UsageError("Specify --keep-last, --older-than, or both.")

    with _open_backup_client(ctx, base_url) as api_client:
        candidates = _select_prune_candidates(
            _json_response(api_client.get("/backups")),
            keep_last=keep_last,
            older_than=older_than,
        )
        ids = [meta["id"] for meta in candidates if "id" in meta]
        base_result = {"dry_run": dry_run, "matched": candidates}
        if dry_run or not ids:
            print_json({**base_result, "deleted": [], "failed": []})
            return

        if not yes:
            _confirm_delete(len(ids))

        print_json({**base_result, **_delete_backups(api_client, ids)})


@backup_group.command("delete")
@click.argument("backup_ids", nargs=-1, required=True)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@_base_url_option
@click.pass_context
def delete_cmd(
    ctx: click.Context,
    backup_ids: tuple[str, ...],
    yes: bool,
    base_url: Optional[str],
) -> None:
    """Delete one or more backups."""
    ids = list(dict.fromkeys(backup_ids))
    if not yes:
        _confirm_delete(len(ids))

    with _open_backup_client(ctx, base_url) as api_client:
        print_json(_delete_backups(api_client, ids))

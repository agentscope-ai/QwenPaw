# -*- coding: utf-8 -*-
"""Manage server-owned workspace root registrations."""

from __future__ import annotations

from pathlib import Path

import click

from ..config.paths import (
    register_agent_workspace_root,
    resolve_agent_workspace_roots,
    unregister_agent_workspace_root,
)


@click.group("workspace-root")
def workspace_roots_group() -> None:
    """Manage trusted roots used for agent workspaces."""


@workspace_roots_group.command("list")
def list_workspace_roots() -> None:
    """List registered workspace roots."""
    for root_id, root in resolve_agent_workspace_roots().items():
        click.echo(f"{root_id}\t{root}")


@workspace_roots_group.command("add")
@click.option("--id", "root_id", required=True, help="Opaque root ID.")
@click.option(
    "--path",
    "root_path",
    required=True,
    type=click.Path(
        path_type=Path,
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    help="Existing local directory to register.",
)
def add_workspace_root(root_id: str, root_path: Path) -> None:
    """Register an existing local directory."""
    try:
        registered = register_agent_workspace_root(root_id, root_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Registered workspace root '{root_id}': {registered}")


@workspace_roots_group.command("remove")
@click.argument("root_id")
def remove_workspace_root(root_id: str) -> None:
    """Remove a registration without deleting its directory."""
    try:
        removed = unregister_agent_workspace_root(root_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if not removed:
        raise click.ClickException(
            f"Workspace root ID '{root_id}' is not registered",
        )
    click.echo(f"Removed workspace root registration '{root_id}'")


__all__ = ["workspace_roots_group"]

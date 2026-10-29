# -*- coding: utf-8 -*-
"""Inspect unknown receipts and record operator notes without resending."""

from pathlib import Path
import json
import sqlite3

import click

from ..channel_protocol.response_receipts import (
    ResponseReceiptStore,
    receipt_key,
    receipt_path,
)


@click.group("receipts")
@click.option("--workspace", type=click.Path(path_type=Path, file_okay=False))
@click.option("--agent-id", default="default", show_default=True)
@click.option(
    "--channel",
    required=True,
    help="Channel key owning the receipts.",
)
@click.option(
    "--namespace",
    help="Driver state key; defaults to CHANNEL.shared.responses.",
)
@click.pass_context
def receipts_group(ctx, workspace, agent_id, channel, namespace):
    """List archived unknown results or annotate manual reconciliation."""
    if workspace is None:
        from ..config import load_config

        profile = load_config().agents.profiles.get(agent_id)
        if profile is None:
            raise click.ClickException(f"Unknown agent: {agent_id}")
        workspace = Path(profile.workspace_dir)
    ctx.obj = (
        ResponseReceiptStore(receipt_path(workspace, channel)),
        namespace or channel + ".shared.responses",
    )


@receipts_group.command("list")
@click.option(
    "--limit",
    type=click.IntRange(1, 1000),
    default=100,
    show_default=True,
)
@click.option(
    "--offset",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
)
@click.pass_obj
def list_cmd(scope, limit, offset):
    """Export one bounded page as JSON; advance offset for the next page."""
    store, namespace = scope
    try:
        rows = store.list(namespace, limit=limit, offset=offset)
    except (ValueError, sqlite3.Error, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(rows, ensure_ascii=False, indent=2))


@receipts_group.command("resolve")
@click.argument("handle")
@click.option(
    "--note",
    required=True,
    help="Explicit manual reconciliation note.",
)
@click.pass_obj
def resolve_cmd(scope, handle, note):
    """Record an operator note while preserving the unknown result and fence."""
    store, namespace = scope
    try:
        row = store.resolve(receipt_key(namespace, handle), note)
    except (ValueError, sqlite3.Error, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(row, ensure_ascii=False, indent=2))

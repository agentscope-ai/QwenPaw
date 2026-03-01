# -*- coding: utf-8 -*-
"""CLI commands for API token management."""
from __future__ import annotations

from datetime import datetime

import click

from ..app.auth.models import TokenScope
from ..app.auth.store import TokenStore
from ..constant import TOKENS_FILE, WORKING_DIR


def _get_store() -> TokenStore:
    return TokenStore(path=WORKING_DIR / TOKENS_FILE)


@click.group("token")
def token_group() -> None:
    """Manage API tokens."""


# ---------------------------------------------------------------
# create
# ---------------------------------------------------------------


@token_group.command("create")
@click.option(
    "--scope",
    type=click.Choice(["owner", "collaborator", "viewer"]),
    default="owner",
    help="Token permission level",
)
@click.option("--label", default="", help="Optional label for the token")
def create_cmd(scope: str, label: str) -> None:
    """Create a new API token."""
    store = _get_store()
    plaintext = store.create(scope=TokenScope(scope), label=label)
    click.echo()
    click.echo(click.style("  Token created successfully!", fg="green"))
    click.echo()
    click.echo(f"  Token:  {plaintext}")
    click.echo(f"  Scope:  {scope}")
    if label:
        click.echo(f"  Label:  {label}")
    click.echo()
    click.echo(
        click.style(
            "  Save this token — it will not be shown again.",
            fg="yellow",
        ),
    )
    click.echo()


# ---------------------------------------------------------------
# list
# ---------------------------------------------------------------


@token_group.command("list")
def list_cmd() -> None:
    """List all API tokens."""
    store = _get_store()
    tokens = store.list_tokens()
    if not tokens:
        click.echo("No tokens configured.")
        return
    click.echo()
    click.echo(f"  {'ID':<14s}  {'Scope':<14s}  {'Label':<20s}  Created")
    click.echo(f"  {'─' * 70}")
    for t in tokens:
        created = datetime.fromtimestamp(t.created_at).strftime("%Y-%m-%d %H:%M")
        click.echo(
            f"  {t.id:<14s}  {t.scope.value:<14s}  {t.label or '—':<20s}  {created}",
        )
    click.echo()


# ---------------------------------------------------------------
# revoke
# ---------------------------------------------------------------


@token_group.command("revoke")
@click.argument("token_id")
def revoke_cmd(token_id: str) -> None:
    """Revoke (delete) a token by its ID."""
    store = _get_store()
    ok = store.revoke(token_id)
    if ok:
        click.echo(click.style(f"  Token {token_id} revoked.", fg="green"))
    else:
        click.echo(click.style(f"  Token {token_id} not found.", fg="red"))

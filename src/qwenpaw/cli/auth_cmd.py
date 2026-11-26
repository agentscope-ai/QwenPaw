# -*- coding: utf-8 -*-
from __future__ import annotations

import click

from ..app.auth import is_auth_enabled, registered_username, reset_password


@click.group("auth", help="Manage web authentication.")
def auth_group() -> None:
    """Manage web authentication."""


@auth_group.command("reset-password")
def reset_password_cmd() -> None:
    """Reset the password for the registered web user."""
    if not is_auth_enabled():
        click.echo(
            "Authentication is not enabled.\n"
            "Set QWENPAW_AUTH_ENABLED=true to enable it first.",
        )
        return

    try:
        username = registered_username()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if username is None:
        click.echo("No registered user found. Nothing to reset.")
        return

    click.echo(f"Resetting password for user: {username}")

    new_password = click.prompt(
        "New password",
        hide_input=True,
        confirmation_prompt=True,
    )

    try:
        updated = reset_password(new_password)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if not updated:
        click.echo("No registered user found. Nothing to reset.")
        return
    click.echo(
        "✓ Password reset successfully. "
        "All existing sessions have been invalidated.",
    )

# -*- coding: utf-8 -*-
from __future__ import annotations

import click

from ..app.auth import is_auth_enabled


@click.group("auth", help="Manage web authentication.")
def auth_group() -> None:
    """Manage web authentication."""


@auth_group.command("reset-password")
def reset_password_cmd() -> None:
    """Password management moved to the external identity provider."""
    if not is_auth_enabled():
        click.echo(
            "Authentication is not enabled.\n"
            "Set QWENPAW_AUTH_ENABLED=true to enable it first.",
        )
        return

    click.echo(
        "QwenPaw no longer owns a local account: users and passwords are "
        "managed by the external identity provider (NocoBase).\n"
        "Reset the password from your NocoBase console instead.",
    )

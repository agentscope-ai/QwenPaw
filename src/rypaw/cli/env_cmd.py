# -*- coding: utf-8 -*-
"""CLI commands for environment variable management."""
from __future__ import annotations

import click

from ..envs import load_envs, set_env_var, delete_env_var


@click.group("env")
def env_group() -> None:
    """Manage environment variables."""


# ---------------------------------------------------------------
# list
# ---------------------------------------------------------------


@env_group.command("list")
def list_cmd() -> None:
    """List all environment variables."""
    envs = load_envs()
    if not envs:
        click.echo("No environment variables configured.")
        return
    click.echo(f"\n  {'Key':<30s}  Value")
    click.echo(f"  {'─' * 56}")
    for key in sorted(envs):
        click.echo(f"  {key:<30s}  {envs[key]}")
    click.echo()


# ---------------------------------------------------------------
# set
# ---------------------------------------------------------------


@env_group.command("set")
@click.argument("key")
@click.argument("value")
def set_cmd(key: str, value: str) -> None:
    """Set an environment variable (KEY VALUE)."""
    set_env_var(key, value)
    click.echo(f"✓ {key} = {value}")


# ---------------------------------------------------------------
# delete
# ---------------------------------------------------------------


@env_group.command("delete")
@click.argument("key")
def delete_cmd(key: str) -> None:
    """Delete an environment variable."""
    envs = load_envs()
    if key not in envs:
        click.echo(
            click.style(
                f"Env var '{key}' not found.",
                fg="red",
            ),
        )
        raise SystemExit(1)
    delete_env_var(key)
    click.echo(f"✓ Deleted: {key}")


# ---------------------------------------------------------------
# Interactive helper (used by init_cmd)
# ---------------------------------------------------------------


def configure_env_interactive() -> None:
    """Interactively add/edit environment variables."""
    from .utils import prompt_confirm

    while True:
        key = click.prompt(
            "  Variable name",
            default="",
            show_default=False,
        ).strip()
        if not key:
            break
        envs = load_envs()
        current = envs.get(key, "")
        value = click.prompt(
            f"  Value for {key}",
            default=current or "",
            show_default=bool(current),
        )
        set_env_var(key, value)
        click.echo(f"  ✓ {key} = {value}")
        if not prompt_confirm("Add another variable?", default=False):
            break
    click.echo("Environment variable configuration complete.")

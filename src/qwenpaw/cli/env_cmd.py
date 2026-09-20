# -*- coding: utf-8 -*-
"""CLI commands for environment variable management."""
from __future__ import annotations

import os
from urllib.parse import quote

import click
import httpx

from ..envs import delete_env_var, load_envs, set_env_var
from ..envs.registry import (
    ENV_VAR_SPECS_BY_KEY,
    validate_env_key,
    validate_env_value,
)
from ..utils.runtime_api import api_client, read_runtime_api


def _managed_envs(
    method: str = "GET",
    key: str | None = None,
    value: str | None = None,
) -> dict[str, str] | None:
    """Apply managed CLI changes in the owning runtime process."""
    if not os.environ.get("QWENPAW_RUNTIME_ID"):
        return None
    endpoint = read_runtime_api()
    if endpoint is None:
        raise click.ClickException("Managed runtime endpoint is unavailable")
    host, port = endpoint
    path = "/api/envs"
    if method == "DELETE":
        path = f"{path}/{quote(key or '', safe='')}"
        if key in ENV_VAR_SPECS_BY_KEY:
            method = "POST"
            path = f"{path}/reset"
    try:
        with api_client(f"http://{host}:{port}") as client:
            response = client.request(
                method,
                path,
                json={key: value} if method == "PATCH" else None,
            )
            response.raise_for_status()
            return {item["key"]: item["value"] for item in response.json()}
    except httpx.HTTPError as exc:
        raise click.ClickException(
            f"Managed runtime environment request failed: {exc}",
        ) from exc


@click.group("env")
def env_group() -> None:
    """Manage environment variables."""


# ---------------------------------------------------------------
# list
# ---------------------------------------------------------------


@env_group.command("list")
def list_cmd() -> None:
    """List all environment variables."""
    managed = _managed_envs()
    envs = load_envs() if managed is None else managed
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
    try:
        validate_env_key(key)
        validate_env_value(key, value)
        if _managed_envs("PATCH", key, value) is None:
            set_env_var(key, value)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✓ {key} = {value}")


# ---------------------------------------------------------------
# delete
# ---------------------------------------------------------------


@env_group.command("delete")
@click.argument("key")
def delete_cmd(key: str) -> None:
    """Delete an environment variable."""
    if _managed_envs("DELETE", key) is not None:
        click.echo(f"✓ Deleted: {key}")
        return
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
        try:
            validate_env_key(key)
            validate_env_value(key, value)
            set_env_var(key, value)
        except ValueError as exc:
            click.echo(click.style(f"  {exc}", fg="red"))
            continue
        click.echo(f"  ✓ {key} = {value}")
        if not prompt_confirm("Add another variable?", default=False):
            break
    click.echo("Environment variable configuration complete.")

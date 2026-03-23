# -*- coding: utf-8 -*-
"""CLI commands for managing agents."""
from __future__ import annotations

from typing import Optional

import click

from .http import client, print_json


def _base_url(ctx: click.Context, base_url: Optional[str]) -> str:
    """Resolve base_url with priority:
    1) command --base-url
    2) global --host/--port (from ctx.obj)
    """
    if base_url:
        return base_url.rstrip("/")
    host = (ctx.obj or {}).get("host", "127.0.0.1")
    port = (ctx.obj or {}).get("port", 8088)
    return f"http://{host}:{port}"


@click.group("agents")
def agents_group() -> None:
    """Manage agents - list and view agent information.

    Use 'list' to see all configured agents.
    """


@agents_group.command("list")
@click.option(
    "--base-url",
    default=None,
    help=(
        "Override the API base URL (e.g. http://127.0.0.1:8088). "
        "If omitted, uses global --host and --port from config."
    ),
)
@click.pass_context
def list_agents(ctx: click.Context, base_url: Optional[str]) -> None:
    """List all configured agents.

    Shows agent ID, name, description, and workspace directory.
    Useful for discovering available agents for inter-agent communication.

    \b
    Examples:
      copaw agents list
      copaw agents list --base-url http://192.168.1.100:8088
    """
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        r = c.get("/agents")
        r.raise_for_status()
        print_json(r.json())

# -*- coding: utf-8 -*-
"""CLI commands for managing plans via HTTP API (/plan)."""
from __future__ import annotations

from typing import Optional

import click

from .http import client, resolve_base_url


@click.group("plan")
def plan_group() -> None:
    """Manage agent plans via the HTTP API (/plan).

    \b
    Examples:
      qwenpaw plan status              # Show current plan
      qwenpaw plan finish              # Finish the current plan
    """


@plan_group.command("status")
@click.option(
    "--base-url",
    default=None,
    help="Override API base URL",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def plan_status(
    ctx: click.Context,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Show the current plan state."""
    base_url = resolve_base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.get("/plan/current", headers=headers)
        r.raise_for_status()
        data = r.json()
        if data is None:
            click.echo("No active plan.")
            return
        _print_plan_table(data)


@plan_group.command("finish")
@click.option(
    "--state",
    type=click.Choice(["done", "abandoned"]),
    default="done",
    help="Final state (done or abandoned)",
)
@click.option(
    "--outcome",
    default="",
    help="Outcome description",
)
@click.option(
    "--base-url",
    default=None,
    help="Override API base URL",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def plan_finish(
    ctx: click.Context,
    state: str,
    outcome: str,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Finish or abandon the current plan."""
    base_url = resolve_base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post(
            "/plan/finish",
            json={"state": state, "outcome": outcome},
            headers=headers,
        )
        r.raise_for_status()
        click.echo(f"Plan marked as '{state}'.")


def _print_plan_table(plan: dict) -> None:
    """Pretty-print a plan state dict."""
    click.echo(f"\n  Plan: {plan.get('name', 'N/A')}")
    click.echo(f"  State: {plan.get('state', 'N/A')}")
    click.echo(f"  ID: {plan.get('plan_id', 'N/A')}")
    click.echo(f"  Created: {plan.get('created_at', 'N/A')}")
    click.echo("")

    subtasks = plan.get("subtasks", [])
    if not subtasks:
        click.echo("  (no subtasks)")
        return

    status_icons = {
        "todo": "[ ]",
        "in_progress": "[>]",
        "done": "[x]",
        "abandoned": "[-]",
    }
    for st in subtasks:
        icon = status_icons.get(st.get("state", "todo"), "[ ]")
        click.echo(f"  {icon} {st.get('name', 'N/A')}")
    click.echo("")

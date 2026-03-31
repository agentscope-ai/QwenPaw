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
      copaw plan status              # Show current plan
      copaw plan history             # List historical plans
      copaw plan finish              # Finish the current plan
      copaw plan recover <plan_id>   # Recover a plan
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


@plan_group.command("history")
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
def plan_history(
    ctx: click.Context,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """List all historical plans."""
    base_url = resolve_base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.get("/plan/history", headers=headers)
        r.raise_for_status()
        data = r.json()
        if not data:
            click.echo("No historical plans.")
            return
        for item in data:
            done = item.get("completed_count", 0)
            total = item.get("subtask_count", 0)
            click.echo(
                f"  {item['plan_id'][:8]}  "
                f"{item['state']:<12} "
                f"[{done}/{total}]  "
                f"{item['name']}  "
                f"({item['created_at']})",
            )


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


@plan_group.command("recover")
@click.argument("plan_id")
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
def plan_recover(
    ctx: click.Context,
    plan_id: str,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Recover a historical plan by ID."""
    base_url = resolve_base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post(f"/plan/recover/{plan_id}", headers=headers)
        r.raise_for_status()
        data = r.json()
        click.echo(f"Plan '{data.get('name', plan_id)}' recovered.")
        _print_plan_table(data)


@plan_group.command("create")
@click.option(
    "--name",
    prompt="Plan name",
    help="Plan name",
)
@click.option(
    "--description",
    prompt="Description",
    help="Plan description",
)
@click.option(
    "--expected-outcome",
    prompt="Expected outcome",
    help="Expected outcome",
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
def plan_create(
    ctx: click.Context,
    name: str,
    description: str,
    expected_outcome: str,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Interactively create a new plan."""
    subtasks = []
    click.echo("Add subtasks (enter empty name to finish):")
    while True:
        st_name = click.prompt(
            "  Subtask name",
            default="",
            show_default=False,
        )
        if not st_name.strip():
            break
        st_desc = click.prompt("  Description")
        st_outcome = click.prompt("  Expected outcome")
        subtasks.append(
            {
                "name": st_name,
                "description": st_desc,
                "expected_outcome": st_outcome,
            },
        )
    if not subtasks:
        click.echo("No subtasks added. Aborting.")
        return

    base_url = resolve_base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post(
            "/plan/create",
            json={
                "name": name,
                "description": description,
                "expected_outcome": expected_outcome,
                "subtasks": subtasks,
            },
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        click.echo(f"Plan '{data.get('name')}' created.")
        _print_plan_table(data)


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

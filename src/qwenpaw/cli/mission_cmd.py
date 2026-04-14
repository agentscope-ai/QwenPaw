# -*- coding: utf-8 -*-
"""CLI entry for Mission Mode — ``qwenpaw mission``."""
from __future__ import annotations

import click

from .http import client, print_json, resolve_base_url


@click.group("mission")
def mission_group():
    """Mission Mode — autonomous iterative agent for complex tasks."""


@mission_group.command("start")
@click.argument("task", nargs=-1, required=True)
@click.option("--agent", default="default", help="Agent ID to use.")
@click.option(
    "--verify",
    default="",
    help="Verification command (e.g. pytest).",
)
@click.option(
    "--max-iterations",
    default=20,
    type=int,
    help="Max iterations.",
)
@click.option("--base-url", default=None, help="Server base URL.")
@click.pass_context
def mission_start(ctx, task, agent, verify, max_iterations, base_url):
    """Start a mission with a task description.

    Example: qwenpaw mission start "Add authentication to the API"
    """
    task_text = " ".join(task)
    parts = [f"/mission {task_text}"]
    if verify:
        parts.append(f"--verify {verify}")
    if max_iterations != 20:
        parts.append(f"--max-iterations {max_iterations}")
    query = " ".join(parts)

    url = resolve_base_url(ctx, base_url)
    payload = {
        "text": query,
        "session_id": f"mission:{agent}",
        "user_id": "cli",
        "agent_id": agent,
    }
    resp = client(url).post("/api/chat/send", json=payload)
    print_json(resp)


@mission_group.command("status")
@click.option("--agent", default="default", help="Agent ID.")
@click.option("--base-url", default=None, help="Server base URL.")
@click.pass_context
def mission_status(ctx, agent, base_url):
    """Show current mission status."""
    url = resolve_base_url(ctx, base_url)
    payload = {
        "text": "/mission status",
        "session_id": f"mission:{agent}",
        "user_id": "cli",
        "agent_id": agent,
    }
    resp = client(url).post("/api/chat/send", json=payload)
    print_json(resp)


@mission_group.command("list")
@click.option("--agent", default="default", help="Agent ID.")
@click.option("--base-url", default=None, help="Server base URL.")
@click.pass_context
def mission_list(ctx, agent, base_url):
    """List all missions."""
    url = resolve_base_url(ctx, base_url)
    payload = {
        "text": "/mission list",
        "session_id": f"mission:{agent}",
        "user_id": "cli",
        "agent_id": agent,
    }
    resp = client(url).post("/api/chat/send", json=payload)
    print_json(resp)

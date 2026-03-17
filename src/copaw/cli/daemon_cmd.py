# -*- coding: utf-8 -*-
"""CLI daemon subcommands: status, restart, reload-config, version, logs.

Shares execution with in-chat /daemon <sub> via daemon_commands.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import click

from ..app.runner.daemon_commands import (
    DaemonContext,
    run_daemon_logs,
    run_daemon_reload_config,
    run_daemon_restart,
    run_daemon_status,
    run_daemon_version,
)
from ..constant import WORKING_DIR
from ..config import load_config


def _get_agent_workspace(agent_id: str) -> Path:
    """Get agent workspace directory."""
    try:
        config = load_config()
        if agent_id in config.agents.profiles:
            ref = config.agents.profiles[agent_id]
            workspace_dir = Path(ref.workspace_dir).expanduser()
            return workspace_dir
    except Exception:
        pass
    return WORKING_DIR


def _context(agent_id: str) -> DaemonContext:
    working_dir = _get_agent_workspace(agent_id)
    return DaemonContext(
        working_dir=working_dir,
        memory_manager=None,
        restart_callback=None,
    )


@click.group("daemon")
def daemon_group() -> None:
    """Daemon commands: status, restart, reload-config, version, logs."""


@daemon_group.command("status")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def status_cmd(agent_id: str) -> None:
    """Show daemon status (config, working dir, memory manager)."""
    ctx = _context(agent_id)
    click.echo(f"Agent: {agent_id}\n")
    click.echo(run_daemon_status(ctx))


@daemon_group.command("restart")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def restart_cmd(agent_id: str) -> None:
    """Print restart instructions (CLI has no process to restart)."""
    ctx = _context(agent_id)
    click.echo(f"Agent: {agent_id}\n")
    click.echo(asyncio.run(run_daemon_restart(ctx)))


@daemon_group.command("reload-config")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def reload_config_cmd(agent_id: str) -> None:
    """Reload config (re-read from file)."""
    ctx = _context(agent_id)
    click.echo(f"Agent: {agent_id}\n")
    click.echo(run_daemon_reload_config(ctx))


@daemon_group.command("version")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def version_cmd(agent_id: str) -> None:
    """Show version and paths."""
    ctx = _context(agent_id)
    click.echo(f"Agent: {agent_id}\n")
    click.echo(run_daemon_version(ctx))


@daemon_group.command("logs")
@click.option(
    "-n",
    "--lines",
    default=100,
    type=int,
    help="Number of last lines to show (default 100).",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def logs_cmd(lines: int, agent_id: str) -> None:
    """Tail last N lines of WORKING_DIR/copaw.log."""
    ctx = _context(agent_id)
    lines = min(max(1, lines), 2000)
    click.echo(f"Agent: {agent_id}\n")
    click.echo(run_daemon_logs(ctx, lines=lines))

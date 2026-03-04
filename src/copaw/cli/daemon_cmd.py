# -*- coding: utf-8 -*-
"""CLI daemon subcommands: status, restart, reload-config, version, logs.

Shares execution with in-chat /daemon <sub> via daemon_commands.
"""
from __future__ import annotations

import asyncio

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


def _context() -> DaemonContext:
    return DaemonContext(
        working_dir=WORKING_DIR,
        memory_manager=None,
        restart_callback=None,
    )


@click.group("daemon")
def daemon_group() -> None:
    """Daemon commands: status, restart, reload-config, version, logs."""


@daemon_group.command("status")
def status_cmd() -> None:
    """Show daemon status (config, working dir, memory manager)."""
    ctx = _context()
    click.echo(run_daemon_status(ctx))


@daemon_group.command("restart")
def restart_cmd() -> None:
    """Print restart instructions (CLI has no process to restart)."""
    ctx = _context()
    click.echo(asyncio.run(run_daemon_restart(ctx)))


@daemon_group.command("reload-config")
def reload_config_cmd() -> None:
    """Reload config (re-read from file)."""
    ctx = _context()
    click.echo(run_daemon_reload_config(ctx))


@daemon_group.command("version")
def version_cmd() -> None:
    """Show version and paths."""
    ctx = _context()
    click.echo(run_daemon_version(ctx))


@daemon_group.command("logs")
@click.option(
    "-n",
    "--lines",
    default=100,
    type=int,
    help="Number of last lines to show (default 100).",
)
def logs_cmd(lines: int) -> None:
    """Tail last N lines of WORKING_DIR/copaw.log."""
    ctx = _context()
    lines = min(max(1, lines), 2000)
    click.echo(run_daemon_logs(ctx, lines=lines))

# -*- coding: utf-8 -*-
"""``copaw service`` — manage CoPaw as a system service."""
from __future__ import annotations

import sys

import click

from ..service import get_service_manager


def _platform_note() -> str:
    """Return a short description of the backend used on the current OS."""
    if sys.platform == "linux":
        return "systemd"
    elif sys.platform == "darwin":
        return "launchd"
    elif sys.platform == "win32":
        return "Windows Task Scheduler"
    return "unknown"


@click.group("service")
def service_group() -> None:
    """Manage CoPaw as a system service (auto-start on boot)."""


@service_group.command("install")
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Bind host for the CoPaw app.",
)
@click.option(
    "--port",
    default=8088,
    type=int,
    show_default=True,
    help="Bind port for the CoPaw app.",
)
@click.option(
    "--system",
    is_flag=True,
    help="Install as system-wide service (requires root/sudo). "
    "Default is user-level service.",
)
def install_cmd(host: str, port: int, system: bool) -> None:
    """Install CoPaw as a service and enable auto-start.

    \b
    Backend per platform:
      Linux   — systemd user service (or system with --system)
      macOS   — launchd LaunchAgent
      Windows — Task Scheduler (runs at logon)
    """
    click.echo(f"Installing CoPaw service (backend: {_platform_note()})...")
    mgr = get_service_manager()
    mgr.install(host=host, port=port, system=system)


@service_group.command("uninstall")
@click.option("--system", is_flag=True, help="Remove the system-wide service.")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def uninstall_cmd(system: bool, yes: bool) -> None:
    """Stop and remove the CoPaw service."""
    if not yes:
        ok = click.confirm("Remove the CoPaw service?", default=False)
        if not ok:
            click.echo("Cancelled.")
            return
    mgr = get_service_manager()
    mgr.uninstall(system=system)


@service_group.command("start")
@click.option(
    "--system",
    is_flag=True,
    help="Operate on the system-wide service.",
)
def start_cmd(system: bool) -> None:
    """Start the CoPaw service."""
    mgr = get_service_manager()
    mgr.start(system=system)


@service_group.command("stop")
@click.option(
    "--system",
    is_flag=True,
    help="Operate on the system-wide service.",
)
def stop_cmd(system: bool) -> None:
    """Stop the CoPaw service."""
    mgr = get_service_manager()
    mgr.stop(system=system)


@service_group.command("restart")
@click.option(
    "--system",
    is_flag=True,
    help="Operate on the system-wide service.",
)
def restart_cmd(system: bool) -> None:
    """Restart the CoPaw service."""
    mgr = get_service_manager()
    mgr.restart(system=system)


@service_group.command("status")
@click.option("--system", is_flag=True, help="Query the system-wide service.")
def status_cmd(system: bool) -> None:
    """Show the current service status."""
    mgr = get_service_manager()
    output = mgr.status(system=system)
    click.echo(output)


@service_group.command("logs")
@click.option(
    "-n",
    "--lines",
    default=50,
    type=int,
    show_default=True,
    help="Number of recent log lines to show.",
)
@click.option(
    "-f",
    "--follow",
    is_flag=True,
    help="Continuously follow log output.",
)
@click.option("--system", is_flag=True, help="Query the system-wide service.")
def logs_cmd(lines: int, follow: bool, system: bool) -> None:
    """Show recent service logs."""
    mgr = get_service_manager()
    mgr.logs(lines=lines, follow=follow, system=system)

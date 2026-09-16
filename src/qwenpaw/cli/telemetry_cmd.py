# -*- coding: utf-8 -*-
"""Explicit Runtime daily telemetry consent and status."""
import click

from ..constant import WORKING_DIR
from ..utils.daily_telemetry import (
    daily_telemetry_enabled,
    set_daily_telemetry_enabled,
)


@click.command("telemetry")
@click.argument(
    "action",
    type=click.Choice(["enable", "disable", "status"]),
)
def telemetry_cmd(action: str) -> None:
    """Manage daily Runtime telemetry (system info, UUID and UTC date)."""
    if action != "status":
        set_daily_telemetry_enabled(WORKING_DIR, action == "enable")
    enabled = daily_telemetry_enabled(WORKING_DIR)
    state = "enabled" if enabled else "disabled"
    click.echo(f"Daily Runtime telemetry: {state}")
    if action == "enable":
        click.echo(
            "One event per active UTC day: random Runtime UUID, version, "
            "install method, OS, Python, architecture and GPU availability.",
        )
    if action != "status" and enabled != (action == "enable"):
        click.echo("A telemetry opt-out or environment override applies.")

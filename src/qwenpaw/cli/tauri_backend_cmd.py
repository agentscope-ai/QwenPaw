# -*- coding: utf-8 -*-
"""CLI command for the Tauri desktop backend sidecar."""

from __future__ import annotations

import click


@click.command("tauri-backend")
@click.option(
    "--log-level",
    default=None,
    type=click.Choice(
        ["critical", "error", "warning", "info", "debug", "trace"],
        case_sensitive=False,
    ),
    help="Log level for the Tauri backend process.",
)
def tauri_backend_cmd(log_level: str | None) -> None:
    """Run the Python backend used by the Tauri desktop app."""
    from qwenpaw.tauri.entry import main

    main(log_level=log_level)

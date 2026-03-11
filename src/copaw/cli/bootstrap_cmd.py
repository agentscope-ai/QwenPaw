# -*- coding: utf-8 -*-
"""CLI runtime bootstrap command."""
from __future__ import annotations

import click

from ..workspace import ensure_runtime_workspace_initialized


@click.command("bootstrap")
def bootstrap_cmd() -> None:
    """Ensure the working directory scaffold exists without overwriting data."""
    result = ensure_runtime_workspace_initialized()

    click.echo(
        "Workspace bootstrap complete: "
        f"config_created={result.config_created}, "
        f"config_updated={result.config_updated}, "
        f"heartbeat_initialized={result.heartbeat_initialized}, "
        f"md_files_copied={result.md_files_copied}, "
        f"skills_initialized={result.skills_initialized}, "
        f"skills_synced={result.skills_synced}, "
        f"skills_skipped={result.skills_skipped}",
    )

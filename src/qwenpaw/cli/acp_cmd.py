# -*- coding: utf-8 -*-
"""``qwenpaw acp`` — run QwenPaw as an ACP agent over stdio."""
from __future__ import annotations

import asyncio
import logging

import click


@click.command("acp")
@click.option(
    "--agent",
    default=None,
    help="Agent ID to use (defaults to active agent)",
)
@click.option(
    "--workspace",
    default=None,
    type=click.Path(exists=False),
    help="Workspace directory override",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug logging to stderr",
)
@click.option(
    "--local-diagnostics",
    is_flag=True,
    default=False,
    help=(
        "Surface raw unexpected error text to the ACP client. Intended for "
        "local clients that own this ACP subprocess, such as the TUI."
    ),
)
def acp_cmd(
    agent: str | None,
    workspace: str | None,
    debug: bool,
    local_diagnostics: bool,
) -> None:
    """Start QwenPaw as an ACP agent (stdio)."""
    from pathlib import Path

    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    workspace_dir = Path(workspace) if workspace else None

    from ..agents.acp.server import run_qwenpaw_agent

    asyncio.run(
        run_qwenpaw_agent(
            agent_id=agent,
            workspace_dir=workspace_dir,
            local_diagnostics=local_diagnostics,
        ),
    )

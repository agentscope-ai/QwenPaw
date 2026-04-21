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
def acp_cmd(
    agent: str | None,
    workspace: str | None,
    debug: bool,
) -> None:
    """Start QwenPaw as an ACP agent (stdio)."""
    from pathlib import Path

    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    workspace_dir = Path(workspace) if workspace else None

    try:
        from ..agents.acp.server import run_qwenpaw_agent
    except ModuleNotFoundError as exc:
        if exc.name != "acp":
            raise
        raise click.ClickException(
            "ACP support is not installed in this environment. "
            "Reinstall or sync dependencies so the "
            "`agent-client-protocol` package is available.",
        ) from exc

    asyncio.run(
        run_qwenpaw_agent(
            agent_id=agent,
            workspace_dir=workspace_dir,
        ),
    )

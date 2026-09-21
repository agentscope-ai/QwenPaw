# -*- coding: utf-8 -*-
"""Explicit chat-history maintenance commands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import click

from ..app.chats.transcript_migration import migrate_history_transcript
from ..config import load_config


@click.group("history")
def history_group() -> None:
    """Manage durable user-visible chat history."""


@history_group.command("migrate-transcript")
@click.option(
    "--agent",
    "agent_id",
    required=True,
    help="Agent ID whose workspace should be migrated.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Inspect eligible sessions without writing transcript files.",
)
def migrate_transcript(agent_id: str, dry_run: bool) -> None:
    """Explicitly import mapped Scroll history into session transcripts."""
    config = load_config()
    profile = config.agents.profiles.get(agent_id)
    if profile is None:
        raise click.ClickException(f"agent not found: {agent_id}")
    try:
        result = migrate_history_transcript(
            Path(profile.workspace_dir),
            agent_id=agent_id,
            dry_run=dry_run,
        )
    except (FileNotFoundError, OSError, sqlite3.Error, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            result.as_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
    )


__all__ = ["history_group"]

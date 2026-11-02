# -*- coding: utf-8 -*-
"""Explicit maintenance for durable Scroll history."""

from pathlib import Path
import sqlite3

import click

from ..agents.context.scroll.history import HistoryStore


@click.group("history")
def history_group() -> None:
    """Inspect history databases outside normal startup."""


@history_group.command("check")
@click.argument("database", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--repair-fts",
    is_flag=True,
    help="Rebuild a damaged FTS index.",
)
def check_history(database: Path, repair_fts: bool) -> None:
    """Check DATABASE; stop its agent before repairing the index."""
    history = None
    try:
        history = HistoryStore(database)
        history.check_integrity(repair=repair_fts)
    except (sqlite3.Error, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if history is not None:
            history.close()
    click.echo(f"History integrity verified: {database}")

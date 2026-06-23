# -*- coding: utf-8 -*-
"""``qwenpaw history`` — maintenance for the scroll durable history store.

Scroll persists every turn (and full tool output) to a per-agent
``history.db``; with ``history_retention_days=0`` (the default) it is kept
forever, so a long-running agent's store can grow without bound. ``history
purge`` is the operator's on-demand way to trim it: preview how much an age
cutoff would drop, delete it, and optionally VACUUM to reclaim disk.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from ..constant import WORKING_DIR

_DEFAULT_DB = "history.db"


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TiB"


def _resolve_targets(agent: str | None, db: str | None) -> list[Path]:
    """The ``history.db`` files this invocation acts on.

    Explicit ``--db`` wins; then ``--agent`` resolves to that agent's
    workspace; otherwise every agent workspace under ``WORKING_DIR`` is
    scanned. Only existing files are returned — we never create a store here.
    """
    if db:
        return [Path(db).expanduser()]
    if agent:
        return [WORKING_DIR / "workspaces" / agent / _DEFAULT_DB]
    ws_root = WORKING_DIR / "workspaces"
    if not ws_root.exists():
        return []
    return sorted(
        p / _DEFAULT_DB
        for p in ws_root.iterdir()
        if p.is_dir() and (p / _DEFAULT_DB).exists()
    )


@click.group("history")
def history_group() -> None:
    """Maintain the scroll durable history store (history.db)."""


@history_group.command("purge")
@click.option(
    "--days",
    type=click.IntRange(min=1),
    required=True,
    help="Delete history rows older than this many days.",
)
@click.option(
    "--agent",
    default=None,
    help="Target one agent's store (WORKING_DIR/workspaces/<agent>/"
    f"{_DEFAULT_DB}). Default: every agent workspace.",
)
@click.option(
    "--db",
    default=None,
    help="Target an explicit history.db path (overrides --agent).",
)
@click.option(
    "--tool-output-only",
    is_flag=True,
    help="Delete only tool-output rows (the bulk of the bloat), keeping the "
    "conversation turns.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show how much would be deleted, but delete nothing.",
)
@click.option(
    "--vacuum",
    is_flag=True,
    help="After deleting, VACUUM to shrink the file on disk "
    "(purge alone reuses pages but does not reclaim space).",
)
@click.option("--yes", is_flag=True, help="Do not prompt for confirmation.")
def purge_cmd(
    *,
    days: int,
    agent: str | None,
    db: str | None,
    tool_output_only: bool,
    dry_run: bool,
    vacuum: bool,
    yes: bool,
) -> None:
    """Trim durable history older than a cutoff, with a preview first."""
    kinds = ("tool_result",) if tool_output_only else None
    targets = _resolve_targets(agent, db)
    if not targets:
        click.echo("No history.db found to purge.")
        return
    missing = [p for p in targets if not p.exists()]
    for p in missing:
        click.echo(f"skip (not found): {p}")
    targets = [p for p in targets if p.exists()]
    if not targets:
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    scope = "tool-output rows" if tool_output_only else "rows"
    click.echo(f"Cutoff: {scope} older than {days}d (created_at < {cutoff})")

    # Lazy import: keep the scroll machinery off the CLI's hot path.
    from ..agents.context.scroll.history import HistoryStore

    # 1) Preview every target up front so the operator sees the full blast
    #    radius before anything is deleted.
    previews = []
    total_rows = total_bytes = 0
    for path in targets:
        store = HistoryStore(path)
        try:
            est = store.estimate_purge(before=cutoff, kinds=kinds)
        finally:
            store.close()
        previews.append((path, est))
        total_rows += est["rows"]
        total_bytes += est["content_bytes"]
        click.echo(
            f"  {path}: {est['rows']} rows, "
            f"~{_human_bytes(est['content_bytes'])} content",
        )
    click.echo(
        f"Total: {total_rows} rows, ~{_human_bytes(total_bytes)} content "
        f"across {len(targets)} store(s).",
    )

    if dry_run:
        click.echo("dry-run: nothing deleted.")
        return
    if total_rows == 0:
        click.echo("Nothing to purge.")
        return
    if not yes and not click.confirm(
        f"Delete {total_rows} rows from {len(targets)} store(s)?",
        default=False,
    ):
        click.echo("Cancelled.")
        return

    # 2) Delete (and optionally reclaim disk).
    removed = 0
    for path, _est in previews:
        store = HistoryStore(path)
        try:
            removed += store.purge(before=cutoff, kinds=kinds)
            if vacuum:
                store.vacuum()
        finally:
            store.close()
    click.echo(
        f"Removed {removed} rows"
        + (" and vacuumed." if vacuum else ".")
        + ("" if vacuum else " (run with --vacuum to reclaim disk.)"),
    )

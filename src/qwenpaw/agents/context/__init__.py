# -*- coding: utf-8 -*-
"""Pluggable context-management strategies.

The default agent behavior is AgentScope-native compression; injecting a
:class:`ContextManager` replaces it. The only built-in alternative today is the
*scroll* strategy (durable ``history.db`` + an in-context eviction index + a
sandboxed ``recall_history_python`` recall REPL), selected via
``LightContextConfig.strategy == "scroll"``.

:func:`build_scroll_components` is the single entry point the builder calls; it
returns ``None`` for any non-scroll strategy, so the feature is fully opt-in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ContextManager

logger = logging.getLogger(__name__)

__all__ = [
    "ContextManager",
    "ScrollComponents",
    "build_scroll_components",
]

# history.db has no retention by default (keep-forever), so a long-running
# agent's store can grow without bound. Warn when it crosses this size so the
# operator can opt into a retention window. Process-level dedupe keeps a
# long-lived server from re-warning on every agent build.
_DB_SIZE_WARN_BYTES = 10 * 1024**3  # 10 GiB
_DB_SIZE_WARNED: set[str] = set()


@dataclass
class ScrollComponents:
    """The pieces the builder wires when the scroll strategy is active."""

    context_manager: Any  # ScrollContextManager (delegated agent hooks)
    cap_middleware: Any  # ToolResultCapMiddleware (on_acting)
    repl_tool: Any  # raw recall_history_python fn w/ a ``_tool_descriptor``


def _warn_first_run(db_path: Path) -> None:
    """Emit the one-time scroll first-run notice for a workspace.

    Logged (not raised) so it never blocks startup. Fires only when
    ``history.db`` does not yet exist, i.e. the first time scroll wires in
    this workspace — the file's presence suppresses it on every later run.
    """
    logger.warning(
        "scroll is now the DEFAULT context strategy. A durable history "
        "store is being created at %s (this workspace had none). Conversation "
        "turns evicted from the live window are persisted there and recalled "
        "on demand instead of being summarized in place. To restore the "
        "previous behavior, set running.light_context_config.strategy to "
        '"native" in this agent\'s config (agent.json) and restart.',
        db_path,
    )


def _warn_db_size(db_path: Path) -> None:
    """Warn once per process when ``history.db`` has grown past the threshold.

    Sums the main db and its ``-wal`` sidecar (the bulk of uncommitted growth).
    Log-only and best-effort: a stat failure must never block wiring.
    """
    key = str(db_path)
    if key in _DB_SIZE_WARNED:
        return
    try:
        total = db_path.stat().st_size
        wal = db_path.with_name(db_path.name + "-wal")
        if wal.exists():
            total += wal.stat().st_size
    except OSError:
        return
    if total < _DB_SIZE_WARN_BYTES:
        return
    _DB_SIZE_WARNED.add(key)
    logger.warning(
        "scroll history at %s is %.1f GiB and has no retention limit "
        "(history_retention_days=0 keeps everything). To trim it, run "
        "'qwenpaw history purge --days 90 --dry-run' to preview, then again "
        "with --vacuum to delete and reclaim disk; add --tool-output-only to "
        "drop just the bulky tool output and keep the conversation. "
        "(Optional: set running.light_context_config.scroll_config."
        "history_retention_days to a non-zero number of days to auto-purge "
        "old rows on teardown.)",
        db_path,
        total / 1024**3,
    )


def build_scroll_components(
    *,
    agent_config: Any,
    workspace_dir: Any,
    model: Any,
    session_id: str,
    agent_id: str | None = None,
    offloader: Any = None,
) -> ScrollComponents | None:
    """Construct the scroll strategy's components, or ``None`` if not selected.

    Returns ``None`` when ``strategy != "scroll"`` or no workspace is
    available, leaving the agent on its native context management.
    """
    try:
        lcc = agent_config.running.light_context_config
    except Exception:
        logger.info("scroll: no light_context_config; staying native")
        return None
    strategy = getattr(lcc, "strategy", "native")
    if strategy != "scroll" or not workspace_dir:
        logger.info(
            "scroll: NOT wiring (strategy=%r, workspace_dir=%r) — native",
            strategy,
            workspace_dir,
        )
        return None
    logger.info(
        "scroll: wiring components (workspace_dir=%s, session_id=%s)",
        workspace_dir,
        session_id,
    )

    # Imported lazily so the native path never pays for the scroll machinery.
    from .scroll.cap_middleware import ToolResultCapMiddleware
    from .scroll.history import HistoryStore
    from .scroll.manager import ScrollContextManager
    from .scroll.repl import make_recall_history_python

    sc = lcc.scroll_config
    db_path = Path(workspace_dir) / sc.db_filename
    # First-run notice: scroll is the default as of this release, so agents
    # that never set ``strategy`` are switched to it silently. The first time
    # we wire scroll in a workspace we create ``history.db`` there; warn once
    # (the file's absence is the first-run signal — it never repeats) so the
    # switch, the new on-disk file, and the rollback path are all discoverable.
    if not db_path.exists():
        _warn_first_run(db_path)
    else:
        # Existing store: nudge toward a retention window if it grew large.
        _warn_db_size(db_path)
    history = HistoryStore(db_path)
    scratch_root = str(Path(workspace_dir) / ".scroll")

    # Shared {tool_call_id -> seq} of results the cap middleware already
    # wrote in full. The manager consults it so it never re-persists the
    # truncated stub the model sees in-context (which would duplicate the row
    # + bloat FTS); it adopts the cap's seq so the result still falls inside
    # the eviction span.
    capped_results: dict[str, int] = {}

    manager = ScrollContextManager(
        history=history,
        session_id=session_id,
        agent_id=agent_id,
        pinned=sc.pinned,
        capped_results=capped_results,
        # Legacy dialog archive is opt-in; only hand the manager an offloader
        # when configured, so by default scroll writes nothing to dialog/.
        offloader=offloader if getattr(sc, "offload_dialog", False) else None,
    )
    cap = ToolResultCapMiddleware(
        history=history,
        model=model,
        session_id=session_id,
        agent_id=agent_id,
        token_cap=sc.tool_output_token_cap,
        capped_results=capped_results,
    )
    tool = make_recall_history_python(
        history_db_path=str(history.path),
        session_id=session_id,
        agent_id=agent_id,
        scratch_root=scratch_root,
        timeout_s=sc.repl_timeout_s,
        allow_unsandboxed=sc.allow_unsandboxed,
    )
    return ScrollComponents(
        context_manager=manager,
        cap_middleware=cap,
        repl_tool=tool,
    )

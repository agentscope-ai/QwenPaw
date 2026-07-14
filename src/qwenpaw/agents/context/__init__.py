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
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ContextManager

logger = logging.getLogger(__name__)

__all__ = [
    "ContextManager",
    "ScrollComponents",
    "build_scroll_components",
    "scroll_unsandboxed_allowed",
]

# Deployment-layer gate for the unsandboxed-recall escape hatch. Only an
# operator who can set process env vars may flip this on — never an agent.json
# / API payload. See scroll_unsandboxed_allowed.
_UNSANDBOXED_ENV = "QWENPAW_ALLOW_UNSANDBOXED_RECALL"
_TRUTHY = {"1", "true", "yes", "on"}


def scroll_unsandboxed_allowed(scroll_config: Any) -> bool:
    """Whether scroll's recall REPL may run WITHOUT a sandbox.

    SECURITY: running recall unsandboxed executes model-authored Python as the
    agent user with zero isolation. In a multi-tenant deployment an untrusted
    ``agent.json`` / API payload must never be able to turn the sandbox off on
    its own — that would be a privilege-escalation path. So this escape hatch
    is gated by the deployment-layer ``QWENPAW_ALLOW_UNSANDBOXED_RECALL`` env
    var; the per-agent ``scroll_config.allow_unsandboxed`` flag is honored ONLY
    when that env var also grants it. Default-deny: if either is missing,
    recall stays sandboxed (or, with no sandbox available, refuses to run).
    """
    if os.environ.get(_UNSANDBOXED_ENV, "").strip().lower() not in _TRUTHY:
        return False
    return bool(getattr(scroll_config, "allow_unsandboxed", False))


# history.db auto-purges past history_retention_days (default 30), but an
# operator can disable that (set 0) or a very chatty agent can outpace it, so
# the store may still grow large. Warn when it crosses this size. Process-level
# dedupe keeps a long-lived server from re-warning on every agent build.
_DB_SIZE_WARN_BYTES = 1 * 1024**3  # 1 GiB
_DB_SIZE_WARNED: set[str] = set()


@dataclass
class ScrollComponents:
    """The pieces the builder wires when the scroll strategy is active."""

    context_manager: Any  # ScrollContextManager (delegated agent hooks)
    repl_tool: Any  # raw recall_history_python fn w/ a ``_tool_descriptor``
    recall_tool: Any  # raw structured recall_history fn (in-process, no
    # sandbox) — the front door for expand/search/recall_tool lookups


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
        "scroll history at %s is %.1f GiB. Rows older than "
        "history_retention_days (default 30) auto-purge on startup and on "
        "teardown; if you set history_retention_days=0 the store keeps "
        "everything and grows without bound. Lower the retention window to "
        "trim it.",
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
    _ = model  # Kept for builder API compatibility.
    logger.info(
        "scroll: wiring components (workspace_dir=%s, session_id=%s)",
        workspace_dir,
        session_id,
    )

    # Everything below is guarded: if any scroll dependency is unsatisfied
    # (a lazy import fails, e.g. a missing package or a broken submodule) or a
    # component can't be constructed, we log and return ``None`` so the agent
    # silently falls back to native context management instead of failing to
    # build. Native keeps full history in-context, so degrading is always safe.
    try:
        # Imported lazily so the native path never pays for the scroll
        # machinery — and so a missing scroll dependency degrades to native
        # here rather than breaking import of this module.
        from .scroll.history import HistoryStore
        from .scroll.manager import ScrollContextManager
        from .scroll.recall_tool import make_recall_history
        from .scroll.repl import make_recall_history_python

        sc = lcc.scroll_config
        trc = lcc.tool_result_pruning_config
        db_path = Path(workspace_dir) / sc.db_filename
        # First-run notice: scroll is the default as of this release, so agents
        # that never set ``strategy`` are switched to it silently. The first
        # time we wire scroll in a workspace we create ``history.db`` there;
        # warn once (the file's absence is the first-run signal — it never
        # repeats) so the switch, the new on-disk file, and the rollback path
        # are all discoverable.
        if not db_path.exists():
            _warn_first_run(db_path)
        else:
            # Existing store: nudge toward a retention window if it grew large.
            _warn_db_size(db_path)
        history = HistoryStore(db_path)
        scratch_root = str(Path(workspace_dir) / ".scroll")

        manager = ScrollContextManager(
            history=history,
            session_id=session_id,
            agent_id=agent_id,
            # Legacy dialog archive is opt-in; only hand the manager an
            # offloader when configured, so by default scroll writes nothing
            # to dialog/.
            offloader=(
                offloader if getattr(sc, "offload_dialog", False) else None
            ),
            summarize_unheadlined=getattr(
                sc,
                "summarize_unheadlined_evictions",
                True,
            ),
            summarize_timeout_s=getattr(
                sc,
                "summarize_eviction_timeout_seconds",
                20,
            ),
            compact_tool_result_max_bytes=(
                trc.pruning_old_msg_max_bytes if trc.enabled else None
            ),
            tool_results_dir=str(
                Path(workspace_dir) / trc.tool_results_cache,
            ),
        )
        tool = make_recall_history_python(
            history_db_path=str(history.path),
            session_id=session_id,
            agent_id=agent_id,
            scratch_root=scratch_root,
            timeout_s=sc.repl_timeout_s,
            allow_unsandboxed=scroll_unsandboxed_allowed(sc),
        )
        # Structured front door for the common recall ops (expand / search /
        # recall_tool): in-process bound queries, no sandbox, no approval —
        # so fold stubs and the eviction index stay readable even where the
        # sandboxed REPL can't run (e.g. Windows without WSL2).
        recall = make_recall_history(
            history_db_path=str(history.path),
            session_id=session_id,
            agent_id=agent_id,
        )
        return ScrollComponents(
            context_manager=manager,
            repl_tool=tool,
            recall_tool=recall,
        )
    except Exception:  # noqa: BLE001 - any scroll failure degrades to native
        logger.warning(
            "scroll: failed to wire components — falling back to native "
            "context management",
            exc_info=True,
        )
        return None

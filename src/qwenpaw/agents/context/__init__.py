# -*- coding: utf-8 -*-
"""Scroll context-management construction.

QwenPaw has one context implementation: durable ``history.db`` storage, an
in-context eviction index, and recall tools. ``QwenPawAgent`` adapts it to
AgentScope's ``_save_to_context`` and ``_compress_context_impl`` hooks.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .scroll.manager import ScrollContextManager

logger = logging.getLogger(__name__)

__all__ = [
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
    """The context and recall pieces wired into an agent."""

    context: "ScrollContextManager"
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
        "Creating the Scroll history store at %s (this workspace had none). "
        "Conversation "
        "turns evicted from the live window are persisted there and recalled "
        "on demand instead of being summarized in place.",
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
    session_id: str,
    agent_id: str | None = None,
    offloader: Any = None,
) -> ScrollComponents:
    """Construct the agent's required Scroll context components."""
    try:
        lcc = agent_config.running.light_context_config
    except Exception as exc:
        raise RuntimeError("scroll requires light_context_config") from exc
    if not workspace_dir:
        raise RuntimeError("scroll requires a workspace directory")
    logger.info(
        "scroll: wiring components (workspace_dir=%s, session_id=%s)",
        workspace_dir,
        session_id,
    )

    history = None
    try:
        from .scroll.history import HistoryStore
        from .scroll.manager import ScrollContextManager
        from .scroll.recall_tool import RecallLoopGuard, make_recall_history
        from .scroll.repl import make_recall_history_python

        sc = lcc.scroll_config
        trc = lcc.tool_result_pruning_config
        db_path = Path(workspace_dir) / sc.db_filename
        # The file's absence is the first-run signal, so the notice never
        # repeats for an initialized workspace.
        if not db_path.exists():
            _warn_first_run(db_path)
        else:
            # Existing store: nudge toward a retention window if it grew large.
            _warn_db_size(db_path)
        history = HistoryStore(db_path)
        recall_loop_guard = RecallLoopGuard()
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
            recall_loop_guard=recall_loop_guard,
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
        # so fold stubs and the eviction index stay readable even when the
        # sandboxed REPL is unavailable.
        recall = make_recall_history(
            history_db_path=str(history.path),
            session_id=session_id,
            agent_id=agent_id,
            loop_guard=recall_loop_guard,
            page_max_bytes=trc.pruning_recent_msg_max_bytes,
        )
        return ScrollComponents(
            context=manager,
            repl_tool=tool,
            recall_tool=recall,
        )
    except Exception as exc:
        if history is not None:
            try:
                history.close()
            except Exception:  # noqa: BLE001 - preserve fallback behavior
                logger.debug(
                    "scroll: failed to close history after wiring failure",
                    exc_info=True,
                )
        raise RuntimeError("failed to initialize scroll context") from exc

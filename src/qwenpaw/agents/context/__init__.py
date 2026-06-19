"""Pluggable context-management strategies.

The default agent behavior is AgentScope-native compression; injecting a
:class:`ContextManager` replaces it. The only built-in alternative today is the
*scroll* strategy (durable ``history.db`` + an in-context eviction index + a
sandboxed ``execute_python`` recall REPL), selected via
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


@dataclass
class ScrollComponents:
    """The pieces the builder wires when the scroll strategy is active."""

    context_manager: Any  # ScrollContextManager (delegated agent hooks)
    cap_middleware: Any  # ToolResultCapMiddleware (on_acting)
    repl_tool: Any  # raw execute_python fn carrying a ``_tool_descriptor``


def build_scroll_components(
    *,
    agent_config: Any,
    workspace_dir: Any,
    model: Any,
    session_id: str,
    run_id: str | None = None,
    task_id: str | None = None,
) -> ScrollComponents | None:
    """Construct the scroll strategy's components, or ``None`` if not selected.

    Returns ``None`` when ``strategy != "scroll"`` or no workspace is available,
    leaving the agent on its native context management.
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
    from .scroll.repl import make_execute_python

    sc = lcc.scroll_config
    history = HistoryStore(Path(workspace_dir) / sc.db_filename)
    scratch_root = str(Path(workspace_dir) / ".scroll")

    manager = ScrollContextManager(
        history=history,
        session_id=session_id,
        run_id=run_id,
        task_id=task_id,
        pinned=sc.pinned,
    )
    cap = ToolResultCapMiddleware(
        history=history,
        model=model,
        session_id=session_id,
        run_id=run_id,
        task_id=task_id,
        token_cap=sc.tool_output_token_cap,
    )
    tool = make_execute_python(
        history_db_path=str(history.path),
        session_id=session_id,
        task_id=task_id,
        scratch_root=scratch_root,
        timeout_s=sc.repl_timeout_s,
    )
    return ScrollComponents(
        context_manager=manager,
        cap_middleware=cap,
        repl_tool=tool,
    )

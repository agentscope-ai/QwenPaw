# -*- coding: utf-8 -*-
"""Mission Mode dispatch for the runner.

Integration layer between ``runner.py`` and the Mission Mode engine:

- Detects ``/mission`` in the user query.
- Delegates command parsing to :mod:`~qwenpaw.agents.ralph.handler`.
- Detects an active mission awaiting user input (Phase 1 follow-up).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from agentscope.message import Msg, TextBlock

from ...agents.ralph.handler import handle_ralph_command, is_ralph_command
from ...agents.ralph.state import (
    get_latest_loop_dir,
    read_loop_config,
)

logger = logging.getLogger(__name__)


# ── Public API ───────────────────────────────────────────────────────────


async def maybe_handle_ralph_command(
    query: str | None,
    msgs: list,
    workspace_dir: Path,
    agent_id: str,
    rewrite_fn: Callable[[list, str], None],
    session_id: str = "",
) -> Msg | dict[str, Any] | None:
    """Handle ``/mission`` if the query matches.

    Returns:
        ``Msg`` for info sub-commands (caller should yield & return).
        ``dict`` with ``{"ralph_phase": 1, "loop_dir": ..., ...}``
            if the caller should enter Mission Phase 1 execution.
        ``None`` if the query is not a mission command.
    """
    if not query or not is_ralph_command(query):
        return None

    result = await handle_ralph_command(
        query=query,
        msgs=msgs,
        workspace_dir=workspace_dir,
        agent_id=agent_id,
        rewrite_fn=rewrite_fn,
        session_id=session_id,
    )

    if isinstance(result, str):
        return Msg(
            name="Friday",
            role="assistant",
            content=[TextBlock(type="text", text=result)],
        )

    if isinstance(result, dict):
        return result

    return None


def detect_active_ralph_phase(
    workspace_dir: Path,
    session_id: str = "",
) -> dict[str, Any] | None:
    """Check if there is an active mission for *this session*.

    When Phase 1 has completed (prd.json exists, current_phase is still
    ``"prd_generation"``), the user's next message should be routed back
    through the Mission agent — the agent itself decides whether the user
    is confirming, requesting changes, or asking questions.

    Session binding: only returns a match when ``session_id`` matches the
    one stored in loop_config.  This prevents unrelated sessions from
    being accidentally captured by an active mission.

    Returns:
        ``dict`` with ``{"ralph_phase": 1 or 2, "loop_dir": ..., ...}``
            when an active mission needs the agent to process user input.
        ``None`` if no active mission for this session.
    """
    loop_dir = get_latest_loop_dir(workspace_dir)
    if loop_dir is None:
        return None

    cfg = read_loop_config(loop_dir)
    phase = cfg.get("current_phase", "")

    if phase not in ("prd_generation", "execution_confirmed"):
        return None

    # Session binding — only match the session that started this loop
    loop_session = cfg.get("session_id", "")
    if loop_session and session_id and loop_session != session_id:
        return None

    if phase == "execution_confirmed":
        return {
            "ralph_phase": 2,
            "loop_dir": str(loop_dir),
            "max_iterations": cfg.get("max_iterations", 20),
        }

    return {
        "ralph_phase": 1,
        "loop_dir": str(loop_dir),
        "max_iterations": cfg.get("max_iterations", 20),
    }

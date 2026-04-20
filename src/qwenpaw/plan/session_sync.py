# -*- coding: utf-8 -*-
"""Session-scoped PlanNotebook lifecycle helpers.

The workspace keeps a single ``PlanNotebook`` instance, but each chat
``session_id`` persists its own serialized state under ``plan_notebook``.
When switching sessions or loading a file without that key, the in-memory
notebook must be reset so stale plans do not leak across sessions.
"""
from __future__ import annotations

import logging
from typing import Any

from .broadcast import broadcast_plan_update
from .hints import set_plan_gate
from .schemas import plan_to_response

logger = logging.getLogger(__name__)

_BOUND_SESSION_ATTR = "_copaw_plan_bound_session_id"


def _get_bound_session_id(nb: Any) -> str:
    """Read the notebook's bound chat session id (best-effort)."""
    if nb is None:
        return ""
    raw = getattr(nb, _BOUND_SESSION_ATTR, "")
    return raw if isinstance(raw, str) else ""


def _bind_session_id(nb: Any, session_id: str) -> None:
    """Bind in-memory notebook to a chat session id."""
    if nb is None:
        return
    setattr(nb, _BOUND_SESSION_ATTR, (session_id or "").strip())


def _repeat_guard_reset(nb: Any) -> None:
    if nb is None:
        return
    if hasattr(nb, "_plan_repeat_fingerprint"):
        nb._plan_repeat_fingerprint = None  # pylint: disable=protected-access
    if hasattr(nb, "_plan_repeat_count"):
        nb._plan_repeat_count = 0  # pylint: disable=protected-access


async def persist_plan_notebook_to_session(
    *,
    session,
    plan_notebook,
    session_id: str,
    user_id: str,
) -> None:
    """Write the in-memory notebook to the chat session JSON.

    Shared by HTTP plan routes and the runner command path so ``/clear`` /
    ``/new`` stay consistent with the session file.
    """
    if plan_notebook is None or not session_id or session is None:
        return
    state_fn = getattr(plan_notebook, "state_dict", None)
    if not callable(state_fn):
        return
    try:
        payload = state_fn()
    except Exception:  # pylint: disable=broad-except
        logger.warning("plan_notebook.state_dict failed", exc_info=True)
        return
    # Pass user_id through unchanged (including "") so filenames match
    # SafeJSONSession._get_save_path ({sid}.json vs default_{sid}.json) for
    # reads in clear_plan_notebook_if_session_has_no_snapshot.
    await session.update_session_state(
        session_id=session_id,
        key="plan_notebook",
        value=payload,
        user_id=user_id,
    )
    _bind_session_id(plan_notebook, session_id)


async def reset_plan_notebook_for_session_switch(
    plan_notebook,
    *,
    agent_id: str,
    outcome: str = "Session switched",
) -> None:
    """Clear active plan state when the session file has no saved notebook."""
    if plan_notebook is None:
        return
    cur = getattr(plan_notebook, "current_plan", None)
    if cur is not None:
        try:
            await plan_notebook.finish_plan(
                state="abandoned",
                outcome=outcome,
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "finish_plan while resetting notebook failed; forcing clear",
                exc_info=True,
            )
            setattr(plan_notebook, "current_plan", None)
    else:
        setattr(plan_notebook, "current_plan", None)

    set_plan_gate(plan_notebook, False)
    if hasattr(plan_notebook, "_plan_needs_reconfirmation"):
        # pylint: disable-next=protected-access
        plan_notebook._plan_needs_reconfirmation = False
    _repeat_guard_reset(plan_notebook)

    try:
        broadcast_plan_update(agent_id, None)
    except Exception:  # pylint: disable=broad-except
        logger.warning("broadcast after notebook reset failed", exc_info=True)


async def clear_plan_notebook_if_session_has_no_snapshot(
    *,
    session,
    plan_notebook,
    session_id: str,
    user_id: str,
    agent_id: str,
) -> None:
    """Drop stale in-memory plan when the session file has no plan_notebook.

    If a snapshot exists, load_session_state loads it; we only reset when
    the key is absent so the singleton notebook does not leak across chats.
    """
    if plan_notebook is None or not session_id:
        return
    sid = (session_id or "").strip()
    raw = await session.get_session_state_dict(session_id, user_id)
    if "plan_notebook" in raw:
        _bind_session_id(plan_notebook, sid)
        return

    # During an ongoing first turn, the session file may not be saved yet.
    # If this notebook is already bound to the same session (or unbound) and
    # currently has an in-memory plan, do not clear it prematurely.
    cur = getattr(plan_notebook, "current_plan", None)
    bound_sid = _get_bound_session_id(plan_notebook)
    if cur is not None and (not bound_sid or bound_sid == sid):
        _bind_session_id(plan_notebook, sid)
        return
    await reset_plan_notebook_for_session_switch(
        plan_notebook,
        agent_id=agent_id,
    )
    _bind_session_id(plan_notebook, sid)


def broadcast_plan_notebook_snapshot(plan_notebook, agent_id: str) -> None:
    """Notify SSE clients after ``load_state_dict`` on the shared notebook."""
    if plan_notebook is None:
        return
    try:
        cur = getattr(plan_notebook, "current_plan", None)
        if cur is None:
            broadcast_plan_update(agent_id, None)
        else:
            payload = plan_to_response(cur).model_dump()
            broadcast_plan_update(agent_id, payload)
    except Exception:  # pylint: disable=broad-except
        logger.warning("broadcast after notebook load failed", exc_info=True)

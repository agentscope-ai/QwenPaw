# -*- coding: utf-8 -*-
"""ProgressStore and ProgressObservingHook for live task progress tracking.

When agent A dispatches a background task to agent B via
``submit_to_agent``, the existing ``check_agent_task`` tool only returns
lifecycle status (submitted / pending / running / finished) - no details.

This module provides:

1. **ProgressStore** - process-level shared registry
   ``(agent_id, session_id)`` -> progress dict.
2. **ProgressObservingHook** - snapshots agent progress into ProgressStore.
   Configured via ``ProgressObservingConfig`` in agent.json.
   Passing ``detail=True`` to ``check_agent_task`` reads this store.
"""

import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

from agentscope.message import Msg

logger = logging.getLogger(__name__)

# Hook type that triggers via PlanNotebook.register_plan_change_hook
PLAN_CHANGE_HOOK_TYPE = "plan_change"


# ---------------------------------------------------------------------------
# ProgressStore
# ---------------------------------------------------------------------------


class _ProgressStore:
    """Process-level in-memory store for agent progress snapshots.

    Keyed by ``(agent_id, session_id)``.  The value is a plain dict with
    at least ``updated_at`` (Unix timestamp) plus any fields written by
    ``ProgressObservingHook``.
    """

    def __init__(self) -> None:
        self._store: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def set(
        self,
        agent_id: str,
        session_id: str,
        data: Dict[str, Any],
    ) -> None:
        self._store[(agent_id, session_id)] = {
            **data,
            "updated_at": time.time(),
        }

    def get(
        self,
        agent_id: str,
        session_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if not session_id:
            # Fall back to the most-recently updated entry for this agent
            candidates = [
                (k, v) for k, v in self._store.items() if k[0] == agent_id
            ]
            if not candidates:
                return None
            return max(candidates, key=lambda x: x[1]["updated_at"])[1]
        return self._store.get((agent_id, session_id))

    def clear(self, agent_id: str, session_id: str) -> None:
        self._store.pop((agent_id, session_id), None)


#: Singleton used by ``ProgressObservingHook`` and ``check_agent_task``.
progress_store = _ProgressStore()


# ---------------------------------------------------------------------------
# ProgressObservingHook
# ---------------------------------------------------------------------------


def _extract_text(msg: Any) -> str:
    """Best-effort extraction of plain text from an agentscope Msg."""
    if msg is None:
        return ""
    if isinstance(msg, Msg):
        content = msg.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "\n".join(parts)
        try:
            return json.dumps(content, ensure_ascii=False)
        except Exception:
            return str(content)
    return str(msg)


class ProgressObservingHook:
    """Snapshot agent progress into ``progress_store`` on every call.

    Register as an *instance hook* (e.g. ``post_acting``) or as a
    PlanNotebook ``plan_change`` hook depending on ``hook_type``.

    Args:
        agent_id: The agent's ``agent_id``.  Used as the store key.
        hook_type: One of the agentscope instance hook types
            (``pre_reply``, ``post_reply``, ``pre_reasoning``,
            ``post_reasoning``, ``pre_acting``, ``post_acting``) **or**
            ``"plan_change"`` for PlanNotebook integration.
    """

    def __init__(self, agent_id: str, hook_type: str = "post_acting") -> None:
        self._agent_id = agent_id
        self._hook_type = hook_type

    # ------------------------------------------------------------------
    # Instance hook signature
    # ------------------------------------------------------------------

    async def __call__(
        self,
        agent: Any,
        kwargs: Dict[str, Any],
        output: Optional[Any] = None,
    ) -> Optional[Dict]:
        """Called by agentscope on every registered instance hook event."""
        try:
            session_id = self._resolve_session_id(agent)
            logger.info(
                "ProgressObservingHook fired: agent_id=%r session_id=%r",
                self._agent_id,
                session_id,
            )
            snapshot: Dict[str, Any] = {
                "hook_type": self._hook_type,
            }

            # Capture latest tool output / model output as a summary
            if output is not None:
                snapshot["last_output"] = _extract_text(output)

            # Capture last message in memory as current context
            last_msg = self._last_memory_msg(agent)
            if last_msg:
                snapshot["last_message"] = last_msg

            progress_store.set(self._agent_id, session_id, snapshot)
            logger.info(
                "ProgressObservingHook stored: store keys=%r",
                list(progress_store._store.keys()),
            )
        except Exception:
            logger.warning(
                "ProgressObservingHook.__call__ failed",
                exc_info=True,
            )
        return None

    # ------------------------------------------------------------------
    # PlanNotebook plan_change hook signature
    # ------------------------------------------------------------------

    def on_plan_change(self, _plan_notebook: Any, plan: Any) -> None:
        """Called by PlanNotebook on every plan state change."""
        try:
            agent = getattr(_plan_notebook, "agent", None)
            session_id = self._resolve_session_id(agent)
            snapshot: Dict[str, Any] = {
                "hook_type": PLAN_CHANGE_HOOK_TYPE,
                "plan": self._serialize_plan(plan),
            }
            progress_store.set(self._agent_id, session_id, snapshot)
        except Exception:
            logger.debug(
                "ProgressObservingHook.on_plan_change failed silently",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_session_id(self, agent: Any) -> str:
        """Extract session_id from agent context or fall back to empty str."""
        try:
            from ...app.agent_context import get_current_session_id

            sid = get_current_session_id()
            if sid:
                return sid
        except Exception:
            pass
        return getattr(agent, "session_id", "") or ""

    def _last_memory_msg(self, agent: Any) -> Optional[str]:
        try:
            memory = getattr(agent, "memory", None)
            if memory is None:
                return None
            content = getattr(memory, "content", None)
            if not content:
                return None
            # Traverse in reverse to find last non-system message
            for msg in reversed(content):
                if getattr(msg, "role", None) not in ("system",):
                    return _extract_text(msg)
        except Exception:
            pass
        return None

    @staticmethod
    def _serialize_plan(plan: Any) -> Any:
        """Convert plan object to a JSON-serialisable value."""
        if plan is None:
            return None
        try:
            if hasattr(plan, "model_dump"):
                return plan.model_dump()
            if hasattr(plan, "__dict__"):
                return plan.__dict__
        except Exception:
            pass
        return str(plan)

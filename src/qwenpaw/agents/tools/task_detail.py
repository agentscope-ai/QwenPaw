# -*- coding: utf-8 -*-
"""Built-in tool for querying detailed progress of a running background task.

When agent A dispatches a background task to agent B via
``submit_to_agent``, the existing ``check_agent_task`` tool only returns
lifecycle status (submitted / pending / running / finished) — no details.

This module provides:

1. **ProgressStore** – process-level shared registry (``agent_id`` → progress).
2. **ProgressObservingHook** – snapshots agent progress into ProgressStore.
   Writes a structured dict per hook_type; if PlanNotebook is enabled,
   adds a plan overlay.  Configured via ``ProgressObservingConfig``.
3. **query_task_detail** – built-in tool that reads ProgressStore and
   returns ``live_status`` (the raw progress dict) plus task lifecycle.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from agentscope.message import Msg
from agentscope.tool import ToolResponse

from .agent_management import (
    _tool_text_response,
    format_background_status_text,
    get_agent_chat_task_status,
    normalize_id,
)

logger = logging.getLogger(__name__)

# Hook type that triggers via PlanNotebook.register_plan_change_hook
PLAN_CHANGE_HOOK_TYPE = "plan_change"


# =========================================================================
# ProgressStore – process-level shared registry
# =========================================================================


class _ProgressStore:
    """Process-level registry mapping ``agent_id`` → progress data.

    Written by ProgressObservingHook (single writer per agent) and read
    by ``query_task_detail`` (read-only).  No locking is needed because
    dict assignment in CPython is atomic under the GIL.
    """

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    def set(self, agent_id: str, progress: Dict[str, Any]) -> None:
        self._data[agent_id] = progress

    def get(self, agent_id: str) -> Dict[str, Any]:
        return self._data.get(agent_id, {})

    def remove(self, agent_id: str) -> None:
        self._data.pop(agent_id, None)


progress_store = _ProgressStore()


# =========================================================================
# Helpers
# =========================================================================


def _truncate(text: str, max_len: int = 300) -> str:
    """Truncate text to max_len with ellipsis indicator."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _extract_plan_overlay(plan: Any) -> Dict[str, Any]:
    """Extract plan progress fields from a Plan object.

    Returns a dict with:
    - plan_name: plan.name
    - plan_progress: "done_count/total" (e.g. "3/5")
    - plan_progress_pct: percentage of done+abandoned subtasks
    - current_subtask: name of the first in_progress subtask, or None
    """
    overlay: Dict[str, Any] = {
        "plan_name": getattr(plan, "name", ""),
    }

    subtasks = getattr(plan, "subtasks", [])
    total = len(subtasks)
    if total > 0:
        done = sum(
            1
            for s in subtasks
            if getattr(s, "state", "") in ("done", "abandoned")
        )
        overlay["plan_progress"] = f"{done}/{total}"
        overlay["plan_progress_pct"] = round(done / total * 100)
        # Find current in-progress subtask
        for s in subtasks:
            if getattr(s, "state", "") == "in_progress":
                overlay["current_subtask"] = getattr(s, "name", "")
                break
        else:
            overlay["current_subtask"] = None
    else:
        overlay["plan_progress"] = "0/0"
        overlay["plan_progress_pct"] = 0
        overlay["current_subtask"] = None

    return overlay


def _extract_tool_output(output: Any) -> str:
    """Extract a short text representation from acting output."""
    if output is None:
        return ""
    if isinstance(output, dict):
        return _truncate(json.dumps(output, ensure_ascii=False), 500)
    if isinstance(output, Msg):
        return _extract_msg_text(output, max_len=500)
    return _truncate(str(output), 500)


def _extract_msg_text(msg: Any, max_len: int = 300) -> str:
    """Extract text content from a Msg object."""
    if msg is None:
        return ""
    if isinstance(msg, Msg):
        text_parts = []
        for block in msg.get_content_blocks():
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "thinking":
                    text_parts.append(block.get("thinking", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        combined = " ".join(text_parts).strip()
        return _truncate(combined, max_len)
    return _truncate(str(msg), max_len)


# =========================================================================
# ProgressObservingHook
# =========================================================================


class ProgressObservingHook:
    """Hook that snapshots agent progress into ProgressStore.

    Each hook type writes a structured dict with two common fields:

    - ``hook_type`` – which hook triggered the write
    - ``last_update`` – Unix timestamp of the write

    Plus type-specific fields.  If PlanNotebook is enabled, a plan
    overlay (``plan_name``, ``plan_progress``, ``plan_progress_pct``,
    ``current_subtask``) is merged in for instance hooks.
    """

    def __init__(self, agent_id: str, hook_type: str = "post_acting") -> None:
        self.agent_id = agent_id
        self.hook_type = hook_type

    # ----- instance hook entry point -----

    async def __call__(
        self,
        agent: Any,
        kwargs: dict[str, Any],
        output: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Instance hook: snapshot agent progress into ProgressStore.

        Works with both pre-hooks (2 args: agent, kwargs) and post-hooks
        (3 args: agent, kwargs, output).

        Returns:
            None (hook doesn't modify kwargs or output).
        """
        try:
            progress = self._build_progress(agent, kwargs, output)
            if progress:
                progress_store.set(self.agent_id, progress)
                logger.debug(
                    "ProgressObservingHook[%s]: agent='%s'",
                    self.hook_type,
                    self.agent_id,
                )
        except Exception:
            logger.exception(
                "ProgressObservingHook error for agent '%s'",
                self.agent_id,
            )

        return None

    # ---- small helpers for each hook type ----

    def _acting_progress(
        self,
        ht: str,
        kwargs: Dict[str, Any],
        output: Any,
    ) -> Dict[str, Any]:
        """Build progress for acting hooks."""
        progress: Dict[str, Any] = {}
        tool_call = kwargs.get("tool_call")
        if tool_call and isinstance(tool_call, dict):
            if ht == "post_acting":
                progress["last_tool"] = tool_call.get("name", "")
                progress["last_tool_input"] = _truncate(
                    json.dumps(
                        tool_call.get("input", {}),
                        ensure_ascii=False,
                    ),
                    500,
                )
            else:  # pre_acting
                progress["current_tool"] = tool_call.get("name", "")
                progress["current_tool_input"] = _truncate(
                    json.dumps(
                        tool_call.get("input", {}),
                        ensure_ascii=False,
                    ),
                    500,
                )
        if ht == "post_acting" and output is not None:
            progress["last_tool_output"] = _extract_tool_output(output)
        return progress

    def _text_progress(
        self,
        ht: str,
        kwargs: Dict[str, Any],
        output: Any,
    ) -> Dict[str, Any]:
        """Build progress for reasoning/reply/observe/print hooks."""
        progress: Dict[str, Any] = {}
        if ht == "post_reasoning" and output is not None:
            progress["last_thought"] = _extract_msg_text(output, max_len=500)
        elif ht == "pre_reasoning":
            progress["status"] = "running"
        elif ht == "post_reply" and output is not None:
            progress["last_reply"] = _extract_msg_text(output, max_len=500)
        elif ht == "pre_reply":
            progress["status"] = "running"
        elif ht in ("pre_observe", "post_observe"):
            msg = kwargs.get("msg")
            if msg is not None:
                progress["last_observed"] = _extract_msg_text(msg, max_len=300)
        elif ht in ("pre_print", "post_print"):
            msg = kwargs.get("msg")
            if msg is not None:
                progress["last_output"] = _extract_msg_text(msg, max_len=300)
        return progress

    def _build_progress(
        self,
        agent: Any,
        kwargs: Dict[str, Any],
        output: Any,
    ) -> Dict[str, Any]:
        """Build the progress dict for the current hook invocation."""
        ht = self.hook_type
        progress: Dict[str, Any] = {
            "hook_type": ht,
            "last_update": time.time(),
        }

        # ---- acting hooks ----
        if ht in ("post_acting", "pre_acting"):
            progress.update(self._acting_progress(ht, kwargs, output))
        else:
            progress.update(self._text_progress(ht, kwargs, output))

        # ---- plan overlay (for all instance hooks) ----
        if ht != PLAN_CHANGE_HOOK_TYPE:
            plan_notebook = getattr(agent, "plan_notebook", None)
            if plan_notebook is not None:
                plan = getattr(plan_notebook, "current_plan", None)
                if plan is not None:
                    progress.update(_extract_plan_overlay(plan))

        return progress

    # ----- plan_change hook entry point -----

    def on_plan_change(self, _plan_notebook: Any, plan: Any) -> None:
        """PlanNotebook plan_change hook: write plan progress to ProgressStore.

        Registered via ``plan_notebook.register_plan_change_hook()``.
        Called every time the plan changes.  If ``plan`` is None (plan
        cleared), the ProgressStore entry for this agent is cleared too.
        """
        try:
            if plan is None:
                progress_store.remove(self.agent_id)
                return

            progress: Dict[str, Any] = {
                "hook_type": PLAN_CHANGE_HOOK_TYPE,
                "last_update": time.time(),
            }
            progress.update(_extract_plan_overlay(plan))
            progress_store.set(self.agent_id, progress)

            logger.debug(
                "ProgressObservingHook[plan_change]: agent='%s' plan='%s'",
                self.agent_id,
                getattr(plan, "name", ""),
            )
        except Exception:
            logger.exception(
                "ProgressObservingHook[plan_change] error for agent '%s'",
                self.agent_id,
            )


# =========================================================================
# Built-in tool
# =========================================================================


async def query_task_detail(
    task_id: str,
    agent_id: Optional[str] = None,
) -> ToolResponse:
    """Query detailed progress of a running background task.

    Unlike ``check_agent_task`` which only returns lifecycle status
    (running / finished / …), this tool also retrieves the executing
    agent's ``live_status`` from the shared ProgressStore when the task
    is running.

    The returned JSON structure:

    .. code-block:: json

        {
          "to_agent": "qa_agent",
          "status": "running",
          "live_status": { ... },
          "task_status": "running",
          "task_result": null
        }

    ``live_status`` is the raw progress dict written by whichever hook
    is configured (see ``ProgressObservingConfig``).  ``task_status``
    and ``task_result`` come from the Task API.

    Args:
        task_id (`str`):
            The background task ID returned by ``submit_to_agent``.
        agent_id (`str`, optional):
            The ID of the agent executing the task.  When provided, the
            tool can look up progress from the shared ProgressStore.

    Returns:
        `ToolResponse`:
            A JSON response with task status and live progress details.
    """
    normalized_task_id = normalize_id(task_id)
    if not normalized_task_id:
        return _tool_text_response(
            "ERROR: 'task_id' is required to query task detail",
        )

    # 1. Get lifecycle status via existing API
    status_result = await asyncio.to_thread(
        get_agent_chat_task_status,
        None,
        normalized_task_id,
        to_agent=None,
        timeout=10,
    )

    status = status_result.get("status", "unknown")

    # 2. Non-running: reuse existing format_background_status_text
    if status != "running":
        return _tool_text_response(
            format_background_status_text(normalized_task_id, status_result),
        )

    # 3. Running: assemble structured result
    result: Dict[str, Any] = {
        "to_agent": status_result.get("to_agent", ""),
        "status": status,
        "live_status": None,
        "task_status": status,
        "task_result": status_result.get("task_result"),
    }

    if agent_id:
        normalized_agent_id = normalize_id(agent_id)
        progress = progress_store.get(normalized_agent_id or "")
        if progress:
            result["live_status"] = progress

    return _tool_text_response(
        json.dumps(result, ensure_ascii=False, indent=2),
    )

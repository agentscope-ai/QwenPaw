# -*- coding: utf-8 -*-
"""on_acting middleware delegating tool execution to ToolCoordinator."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable

from agentscope.middleware import MiddlewareBase

if TYPE_CHECKING:
    from agentscope.agent import Agent

    from ._coordinator import BackgroundResultProcessor, ToolCoordinator

logger = logging.getLogger(__name__)


def _extract_last_assistant_text(agent: "Agent") -> str:
    """Return the current step's reasoning text of the agent, or "".

    Reads ``agent.state.context`` (agentscope 2.0). agentscope's
    ``_save_to_context`` accumulates every turn of one reply into the
    same trailing assistant message, so the per-step reasoning is the
    *trailing run of consecutive* ``type == "text"`` blocks — i.e. the
    text produced after the most recent tool_use/tool_result block.
    Trailing ``tool_use`` blocks (the current turn's tool call may
    already sit at the end) are skipped before collecting. Content
    blocks may be plain dicts or pydantic TextBlock objects, so both
    access styles are supported. Any unexpected structure yields an
    empty string.
    """
    try:
        context = agent.state.context
        if not context:
            return ""
        last_msg = context[-1]
        if getattr(last_msg, "role", None) != "assistant":
            return ""
        content = getattr(last_msg, "content", None)
        if isinstance(content, str):
            return content.strip()
        parts: list[str] = []
        for block in reversed(content or []):
            if isinstance(block, dict):
                block_type = block.get("type")
                block_text = block.get("text")
            else:
                block_type = getattr(block, "type", None)
                block_text = getattr(block, "text", None)
            if block_type == "text":
                if block_text:
                    parts.append(str(block_text))
                continue
            if parts:
                # Hit the previous tool_use/tool_result: the current
                # step's text run is complete.
                break
            if block_type in ("tool_call", "tool_use"):
                # Skip the current turn's trailing tool-call block(s)
                # (agentscope uses "tool_call"; "tool_use" kept for
                # anthropic-style payloads).
                continue
            # A trailing tool_result (or other block) with no text
            # after it: this turn produced no new reasoning text.
            break
        return "\n".join(reversed(parts)).strip()
    except Exception:  # noqa: BLE001
        return ""


def _capture_f1_reasoning(agent: "Agent") -> None:
    """Refresh the F1 reasoning registry from the agent context.

    No-op when the session is missing or F1 is inactive. Empty
    extractions never overwrite a previously captured reason.
    """
    request_context = getattr(agent, "_request_context", None) or {}
    session_id = request_context.get("session_id", "")
    if not session_id:
        return
    try:
        from ..config.context import (
            is_f1_active_for_session,
            set_f1_reasoning,
        )

        if is_f1_active_for_session(session_id):
            reasoning = _extract_last_assistant_text(agent)
            if reasoning:
                set_f1_reasoning(session_id, reasoning)
    except Exception:  # noqa: BLE001
        logger.debug("F1 reasoning capture failed", exc_info=True)


class ToolCoordinatorMiddleware(MiddlewareBase):
    """Thin on_acting middleware delegating to ToolCoordinator.

    Uses agentscope 2.0's official extension point — no Toolkit subclass.
    Direct access to agent.request_context (no ContextVar indirection).
    ``_execute_tool_call`` side effects work automatically.
    """

    def __init__(
        self,
        coordinator: "ToolCoordinator",
        background_result_processor: "BackgroundResultProcessor | None" = None,
    ) -> None:
        self._coordinator = coordinator
        self._background_result_processor = background_result_processor

    async def on_reasoning(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],  # pylint: disable=unused-argument
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        """Capture the F1 step reasoning right after reasoning completes.

        Permission checking (which creates the approval request) runs
        before ``on_acting``, so the reasoning must be refreshed here —
        after ``_save_to_context`` persisted this round's text and
        before the round's tool calls hit the approval gate. Capturing
        only in ``on_acting`` lags the approval card by one full step.
        """
        async for item in next_handler():
            yield item
        _capture_f1_reasoning(agent)

    async def on_acting(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        tool_call = input_kwargs["tool_call"]

        request_context = getattr(agent, "_request_context", None) or {}
        session_id = request_context.get("session_id", "")
        agent_id = request_context.get("agent_id", "")
        root_session_id = request_context.get("root_session_id", "")

        # Fallback refresh (e.g. flows that bypass on_reasoning).
        _capture_f1_reasoning(agent)

        async for item in self._coordinator.execute(
            tool_call=tool_call,
            next_handler=next_handler,
            session_id=session_id,
            agent_id=agent_id,
            root_session_id=root_session_id,
            background_result_processor=self._background_result_processor,
        ):
            yield item

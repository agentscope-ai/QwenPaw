# -*- coding: utf-8 -*-
"""on_acting middleware delegating tool execution to ToolCoordinator."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable

from agentscope.message import TextBlock, ToolResultState
from agentscope.middleware import MiddlewareBase
from agentscope.tool import ToolResponse

if TYPE_CHECKING:
    from agentscope.agent import Agent

    from ._coordinator import BackgroundResultProcessor, ToolCoordinator

logger = logging.getLogger(__name__)

EXEMPT_DEDUP_TOOLS = {
    "check_agent_task",
    "get_task_status",
    "desktop_screenshot",
    "browser_use",
}


def _canonicalize_args(val: Any) -> str:
    if not val:
        return ""
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            return val.strip()
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, sort_keys=True)
        except Exception:
            return str(val)
    return str(val)


def _is_duplicate_call(
    context: list,
    tool_name: str | None,
    tool_input: Any,
) -> bool:
    # ponytail: in-memory context check for duplicate tool calls in
    # the same turn
    if not context or not tool_name:
        return False

    if tool_name in EXEMPT_DEDUP_TOOLS or any(
        x in tool_name for x in ("check", "status", "poll", "wait")
    ):
        return False

    canon_current = _canonicalize_args(tool_input)

    current_turn_msgs = []
    for msg in reversed(context):
        if getattr(msg, "role", None) == "user":
            break
        current_turn_msgs.append(msg)

    for msg in current_turn_msgs:
        if getattr(msg, "role", None) != "assistant":
            continue
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            btype = getattr(block, "type", None) or (
                block.get("type") if isinstance(block, dict) else None
            )
            if btype in ("tool_call", "tool_use"):
                name = getattr(block, "name", None) or (
                    block.get("name") if isinstance(block, dict) else None
                )
                args = getattr(block, "input", None) or (
                    block.get("input") if isinstance(block, dict) else None
                )
                if name == tool_name:
                    if _canonicalize_args(args) == canon_current:
                        return True
    return False


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

    async def on_acting(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        tool_call = input_kwargs["tool_call"]

        tool_name = getattr(tool_call, "name", None) or (
            tool_call.get("name") if isinstance(tool_call, dict) else None
        )
        tool_input = getattr(tool_call, "input", None) or (
            tool_call.get("input") if isinstance(tool_call, dict) else None
        )
        tool_id = getattr(tool_call, "id", None) or (
            tool_call.get("id") if isinstance(tool_call, dict) else None
        )

        state = getattr(agent, "state", None)
        context = getattr(state, "context", []) if state is not None else []
        if _is_duplicate_call(context, tool_name, tool_input):
            logger.warning(
                "Duplicate tool call detected in same turn: %s",
                tool_name,
            )
            yield ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error: Duplicate tool call. You already called "
                            f"`{tool_name}` with these exact arguments in the "
                            f"current turn. Repeating the same call with same "
                            f"arguments will result in a loop. Analyze the "
                            f"previous tool output from this turn, try a "
                            f"different approach, or ask the user if stuck."
                        ),
                    ),
                ],
                id=tool_id,
                state=ToolResultState.ERROR,
            )
            return

        request_context = getattr(agent, "_request_context", None) or {}
        session_id = request_context.get("session_id", "")
        agent_id = request_context.get("agent_id", "")
        root_session_id = request_context.get("root_session_id", "")

        async for item in self._coordinator.execute(
            tool_call=tool_call,
            next_handler=next_handler,
            session_id=session_id,
            agent_id=agent_id,
            root_session_id=root_session_id,
            background_result_processor=self._background_result_processor,
        ):
            yield item

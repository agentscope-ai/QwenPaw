# -*- coding: utf-8 -*-
"""Synchronous context repair helpers for interrupted responses."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# pylint: disable=too-many-branches,too-many-nested-blocks
def inject_partial_response(agent: Any, envelope: Any) -> int:
    """Inject unfinished text/thinking blocks into the agent context.

    Returns the number of blocks added. Dangling tool calls are handled
    separately by :func:`close_dangling_tool_calls`.
    """
    from agentscope.message import (
        TextBlock,
        ThinkingBlock,
    )

    partial = envelope.collect_partial_blocks()
    if not partial:
        return 0

    agent_state = getattr(agent, "state", None)
    context = getattr(agent_state, "context", None) if agent_state else None
    existing_texts: set[str] = set()
    if context:
        last = context[-1]
        if getattr(last, "role", None) == "assistant":
            for block in getattr(last, "content", []) or []:
                if getattr(block, "type", None) == "text":
                    existing_texts.add(getattr(block, "text", ""))
                elif getattr(block, "type", None) == "thinking":
                    existing_texts.add(getattr(block, "thinking", ""))

    blocks: list = []
    for block_type, content in partial:
        if content in existing_texts:
            continue
        if block_type == "thinking":
            blocks.append(ThinkingBlock(thinking=content))
        else:
            blocks.append(TextBlock(text=content))

    if blocks:
        # AgentScope owns this mutation API but exposes it as protected.
        # pylint: disable=protected-access
        agent._save_to_context(blocks)
    return len(blocks)


def close_dangling_tool_calls(  # pylint: disable=too-many-locals
    agent: Any,
    envelope: Any,
) -> int:
    """Append interrupted results for tool calls that have no result."""
    from agentscope.message import (  # pylint: disable=import-outside-toplevel
        ToolCallBlock,
        ToolCallState,
        ToolResultBlock,
        ToolResultState,
    )

    state = getattr(agent, "state", None)
    context = getattr(state, "context", None) if state else None
    if not context:
        return 0

    last_msg = context[-1]
    if getattr(last_msg, "role", None) != "assistant":
        return 0
    if getattr(last_msg, "name", None) != getattr(agent, "name", ""):
        return 0

    content = getattr(last_msg, "content", None)
    if not isinstance(content, list):
        return 0

    awaiting: dict[str, int] = {}
    for idx, block in enumerate(content):
        if isinstance(block, ToolCallBlock):
            awaiting[block.id] = idx
        elif isinstance(block, ToolResultBlock):
            awaiting.pop(block.id, None)

    if not awaiting:
        return 0

    envelope_tool_output = envelope.collect_tool_output()
    interruption_msg = (
        "<system-reminder>The tool call has been interrupted by "
        "the user.</system-reminder>"
    )

    for call_id, idx in awaiting.items():
        block = content[idx]
        block.state = ToolCallState.FINISHED
        output = envelope_tool_output.get(call_id, "")
        if output:
            output += "\n" + interruption_msg
        else:
            output = interruption_msg
        content.append(
            ToolResultBlock(
                id=call_id,
                name=block.name,
                output=output,
                state=ToolResultState.INTERRUPTED,
            ),
        )

    return len(awaiting)


def repair_interrupted_response(agent: Any, envelope: Any) -> None:
    """Best-effort partial response injection and tool-call repair."""
    injected = 0
    closed = 0
    try:
        injected = inject_partial_response(agent, envelope)
    except Exception:
        logger.debug(
            "cancel-save: partial response injection failed",
            exc_info=True,
        )
    try:
        closed = close_dangling_tool_calls(agent, envelope)
    except Exception:
        logger.debug(
            "cancel-save: dangling tool-call repair failed",
            exc_info=True,
        )
    if injected or closed:
        logger.info(
            "cancel-save: injected %d partial block(s), "
            "closed %d dangling tool call(s)",
            injected,
            closed,
        )


__all__ = [
    "close_dangling_tool_calls",
    "inject_partial_response",
    "repair_interrupted_response",
]

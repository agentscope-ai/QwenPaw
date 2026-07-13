# -*- coding: utf-8 -*-
"""Construct hint messages for completed background tool calls."""

from __future__ import annotations

import uuid
from typing import Any


def make_offload_hint_msg(entry: Any) -> Any:
    """Construct a hint Msg for a completed offloaded tool call.

    The hint contains a system-notification TextBlock and a paired tool
    call/result sequence with the finalized response content.
    """
    from agentscope.message import (
        Msg,
        TextBlock,
        ToolCallBlock,
        ToolCallState,
        ToolResultBlock,
    )

    end = entry.end_state or "unknown"
    notification = TextBlock(
        type="text",
        text=(
            "<system-notification>\n"
            f"Background tool call `{entry.ctx.tool_name}` "
            f"(id={entry.ctx.tool_call_id}) completed with state={end}. "
            "The full result follows in the next tool_result block.\n"
            "</system-notification>"
        ),
    )
    hint_tool_call_id = uuid.uuid4().hex
    tool_call = ToolCallBlock(
        type="tool_call",
        id=hint_tool_call_id,
        name=entry.ctx.tool_name,
        input="{}",
        state=ToolCallState.FINISHED,
    )
    tool_result = ToolResultBlock(
        type="tool_result",
        id=hint_tool_call_id,
        name=entry.ctx.tool_name,
        output=list(entry.final_response.content or []),
        state=entry.final_response.state,
    )
    # AgentScope 2.0 validates that system messages contain only text
    # blocks.  This hint must carry a paired tool call/result so provider
    # formatters keep the result on their valid tool-result paths; use the
    # assistant role intentionally.
    return Msg(
        name="system",
        role="assistant",
        content=[notification, tool_call, tool_result],
    )

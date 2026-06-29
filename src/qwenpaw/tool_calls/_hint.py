# -*- coding: utf-8 -*-
"""Construct hint messages for completed background tool calls."""

from __future__ import annotations

from typing import Any


def make_offload_hint_msg(entry: Any) -> Any:
    """Construct a hint Msg for a completed offloaded tool call.

    The hint contains a system-notification TextBlock and a
    ToolResultBlock with the finalized response content.
    """
    from agentscope.message import Msg, TextBlock, ToolResultBlock

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
    tool_result = ToolResultBlock(
        type="tool_result",
        id=entry.ctx.tool_call_id,
        name=entry.ctx.tool_name,
        output=list(entry.final_response.content or []),
        state=entry.final_response.state,
    )
    # AgentScope 2.0 validates that system messages contain only text
    # blocks.  This hint must carry a ToolResultBlock so provider formatters
    # keep it on the tool-result path; use assistant role intentionally.
    return Msg(
        name="system",
        role="assistant",
        content=[notification, tool_result],
    )

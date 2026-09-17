# -*- coding: utf-8 -*-
"""Token accounting helpers for ``/history`` and context inspection."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .as_msg_handler import AsMsgHandler
from .estimate_token_counter import EstimatedTokenCounter

if TYPE_CHECKING:
    from agentscope.state import AgentState


async def estimate_context_tokens(
    state: "AgentState",
    token_counter: EstimatedTokenCounter,
    max_input_length: int,
) -> dict:
    """Compute the per-message and summary token breakdown."""
    handler = AsMsgHandler(token_counter)

    summary = state.summary if isinstance(state.summary, str) else ""
    summary_tokens = await handler.count_str_token(summary)

    messages_detail = [
        await handler.stat_message(msg) for msg in state.context
    ]
    messages_tokens = sum(stat.total_tokens for stat in messages_detail)
    estimated_tokens = messages_tokens + summary_tokens
    usage_ratio = (
        (estimated_tokens / max_input_length * 100)
        if max_input_length > 0
        else 0
    )

    return {
        "total_messages": len(state.context),
        "compressed_summary_tokens": summary_tokens,
        "messages_tokens": messages_tokens,
        "estimated_tokens": estimated_tokens,
        "max_input_length": max_input_length,
        "context_usage_ratio": usage_ratio,
        "messages_detail": messages_detail,
    }


async def format_history_str(
    state: "AgentState",
    token_counter: EstimatedTokenCounter,
    max_input_length: int,
) -> str:
    """Render the ``/history`` reply text."""
    stats = await estimate_context_tokens(
        state,
        token_counter,
        max_input_length,
    )

    lines = []
    for i, msg_stat in enumerate(stats["messages_detail"], 1):
        blocks_info = ""
        if msg_stat.content:
            block_strs = [
                f"{b.block_type}(tokens={b.token_count})"
                for b in msg_stat.content
            ]
            blocks_info = f"\n    content: [{', '.join(block_strs)}]"

        lines.append(
            f"[{i}] **{msg_stat.role}** "
            f"(total_tokens={msg_stat.total_tokens})"
            f"{blocks_info}\n    preview: {msg_stat.preview}",
        )

    return (
        f"**Conversation History**\n\n"
        f"- Total messages: {stats['total_messages']}\n"
        f"- Estimated tokens: {stats['estimated_tokens']}\n"
        f"- Max input length: {stats['max_input_length']}\n"
        f"- Context usage: "
        f"{stats['context_usage_ratio']:.1f}%\n"
        f"- Compressed summary tokens: "
        f"{stats['compressed_summary_tokens']}\n\n" + "\n\n".join(lines)
    )

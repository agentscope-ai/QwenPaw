# -*- coding: utf-8 -*-
"""Thin helpers over agentscope 2.0 ``AgentState``.

After the as2 migration, short-term memory lives on ``agent.state.context``
(``list[Msg]``) and ``agent.state.summary`` (``str``) natively.  The 2.0
``Agent`` reply loop already appends user inputs, model responses, and tool
results to ``state.context`` via ``_save_to_context``; the 2.0 native
``compress_context()`` (driven by ``ContextConfig.trigger_ratio``) handles
summarisation + trimming before each reasoning step.  qwenpaw doesn't need
its own ``Memory`` class anymore.

What stays qwenpaw-specific:

1. **Dialog JSONL persistence** — append messages to
   ``{dialog_path}/{YYYY-mm-dd}.jsonl`` so we have an off-context conversation
   log per day.  Used by ``/new`` (persist-then-clear) and by the
   ``LightContextManager.pre_reasoning`` compactor (currently dormant
   without ``memory_manager``).

2. **Token accounting for /history** — pretty-print the current context
   window with per-message token breakdown via :class:`AsMsgHandler`.

The HINT/COMPRESSED marks from 1.x are *gone*.  2.0's
``ContextConfig.compression_prompt`` covers the system-hint use case; the
COMPRESSED mark was already transient in 1.x (set then immediately deleted),
so removing it loses nothing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
import aiofiles.os

from agentscope.message import Msg

from .as_msg_handler import AsMsgHandler
from ..utils.estimate_token_counter import EstimatedTokenCounter

if TYPE_CHECKING:
    from agentscope.state import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dialog persistence
# ---------------------------------------------------------------------------


async def append_messages_to_dialog(
    messages: list[Msg],
    dialog_path: str | Path | None,
) -> int:
    """Append messages to a ``YYYY-mm-dd.jsonl`` file under ``dialog_path``.

    No-op when ``messages`` is empty or ``dialog_path`` is ``None``.  Groups
    by message date (extracted from ``Msg.timestamp`` — a 1.x alias for
    ``created_at`` provided by ``_compat.__init__``) and sorts within each
    file by timestamp.

    Returns the number of messages actually appended.
    """
    if not messages or dialog_path is None:
        return 0

    dialog_path = Path(dialog_path)
    try:
        await aiofiles.os.makedirs(dialog_path, exist_ok=True)
    except Exception as e:
        logger.exception(
            f"Failed to create dialog directory {dialog_path}: {e}",
        )
        return 0

    messages_by_date: dict[str, list[Msg]] = {}
    for msg in messages:
        try:
            if msg.timestamp:
                date_str = msg.timestamp.split()[0]
            else:
                date_str = datetime.now().strftime("%Y-%m-%d")
            messages_by_date.setdefault(date_str, []).append(msg)
        except Exception as e:
            logger.warning(
                f"Failed to process message timestamp: {e}, "
                f"using today's date",
            )
            date_str = datetime.now().strftime("%Y-%m-%d")
            messages_by_date.setdefault(date_str, []).append(msg)

    total_count = 0
    for date_str, msgs in messages_by_date.items():
        try:
            msgs_sorted = sorted(msgs, key=lambda m: m.timestamp or "")
        except Exception as e:
            logger.warning(f"Failed to sort messages by timestamp: {e}")
            msgs_sorted = msgs

        filepath = dialog_path / f"{date_str}.jsonl"
        try:
            async with aiofiles.open(
                filepath,
                mode="a",
                encoding="utf-8",
            ) as f:
                for msg in msgs_sorted:
                    msg_dict = msg.to_dict()
                    await f.write(
                        json.dumps(msg_dict, ensure_ascii=False) + "\n",
                    )
                    total_count += 1
            logger.info(
                f"Appended {len(msgs_sorted)} messages to {filepath}",
            )
        except Exception as e:
            logger.exception(
                f"Failed to append messages to dialog "
                f"file {filepath}: {e}",
            )

    return total_count


async def persist_and_clear_context(
    state: "AgentState",
    dialog_path: str | Path | None,
) -> int:
    """Persist all messages in ``state.context`` to JSONL then clear it.

    Used by ``/new`` (and any other "reset short-term memory" entry point)
    so we never lose conversation history — it just leaves the model's
    visible window and lives on disk for later review.
    """
    if not state.context:
        return 0
    written = await append_messages_to_dialog(
        list(state.context),
        dialog_path,
    )
    state.context.clear()
    return written


async def persist_compressed(
    state: "AgentState",
    messages: list[Msg],
    dialog_path: str | Path | None,
) -> int:
    """Persist ``messages`` to JSONL then drop them from ``state.context``.

    Used by the qwenpaw compactor path (``LightContextManager.pre_reasoning``)
    when it decides to evict older messages.  Same delete-after-persist
    semantics as the 1.x ``mark_messages_compressed``.
    """
    if not messages:
        return 0

    await append_messages_to_dialog(messages, dialog_path)
    msg_ids = {msg.id for msg in messages}
    initial = len(state.context)
    state.context[:] = [m for m in state.context if m.id not in msg_ids]
    return initial - len(state.context)


# ---------------------------------------------------------------------------
# Token accounting (for /history)
# ---------------------------------------------------------------------------


async def estimate_context_tokens(
    state: "AgentState",
    token_counter: EstimatedTokenCounter,
    max_input_length: int,
) -> dict:
    """Compute the per-message and summary token breakdown for ``/history``."""
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

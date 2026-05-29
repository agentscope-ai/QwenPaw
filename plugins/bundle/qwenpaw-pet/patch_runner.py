# -*- coding: utf-8 -*-
"""Patch QwenPaw AgentRunner from inside the backend plugin."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from emitter import emit_pet_event, schedule_emit_pet_event

logger = logging.getLogger("qwenpaw.pet_desktop")

_ORIGINAL_QUERY_HANDLER = None
_PATCHED = False


def _request_meta(runner: Any, request: Any) -> dict[str, Any]:
    return {
        "agent_id": getattr(runner, "agent_id", "default"),
        "agent_name": getattr(runner, "agent_name", "QwenPaw"),
        "session_id": getattr(request, "session_id", "") if request else "",
        "user_id": getattr(request, "user_id", "") if request else "",
        "channel": getattr(request, "channel", "") if request else "",
    }


def _block_get(block: Any, key: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _iter_blocks(msg: Any):
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    if isinstance(content, list):
        yield from content
    elif isinstance(content, dict):
        yield content
    elif isinstance(content, str) and content.strip():
        yield {"type": "text", "text": content}


def _is_tool_guard_approval_msg(msg: Any) -> bool:
    metadata = getattr(msg, "metadata", None)
    if isinstance(msg, dict):
        metadata = msg.get("metadata", metadata)
    return (
        isinstance(metadata, dict)
        and metadata.get("message_type") == "tool_guard_approval"
    )


def _classify_msg(msg: Any) -> tuple[str | None, str | None]:
    if _is_tool_guard_approval_msg(msg):
        return None, None
    for block in _iter_blocks(msg):
        block_type = _block_get(block, "type")
        if block_type == "tool_use":
            name = _block_get(block, "name") or "tool"
            return "tool.detected", f"Using {str(name)[:40]}"
        if block_type == "tool_result":
            return "tool.result", "Tool result"
        if block_type == "text":
            text = str(_block_get(block, "text") or "").strip()
            if text:
                return "query.first_token", "Replying"
    return None, None


def _split_result(result: Any) -> tuple[Any, bool | None]:
    if isinstance(result, tuple) and len(result) >= 2:
        return result[0], result[1]
    if isinstance(result, list) and len(result) >= 2:
        return result[0], result[1]
    return result, None


def patch_agent_runner() -> None:
    """Install an observing wrapper around AgentRunner.query_handler."""
    global _ORIGINAL_QUERY_HANDLER, _PATCHED

    if _PATCHED:
        return

    from qwenpaw.app.runner.runner import AgentRunner

    _ORIGINAL_QUERY_HANDLER = AgentRunner.query_handler

    async def patched_query_handler(self, msgs, request=None, **kwargs):
        meta = _request_meta(self, request)
        saw_first_output = False
        last_event = None

        schedule_emit_pet_event(
            "query.received",
            text="New message",
            **meta,
        )
        schedule_emit_pet_event("query.running", text="Thinking", **meta)

        try:
            async for result in _ORIGINAL_QUERY_HANDLER(
                self,
                msgs,
                request,
                **kwargs,
            ):
                msg, is_last = _split_result(result)
                event, text = _classify_msg(msg)

                if event and event != last_event:
                    schedule_emit_pet_event(event, text=text, **meta)
                    last_event = event

                if not saw_first_output:
                    saw_first_output = True
                    # Only emit a fallback ``query.first_token`` when the
                    # classifier did not already speak for this chunk —
                    # otherwise we either (a) duplicate ``query.first_token``
                    # on a normal text reply, or (b) bounce the pet through
                    # the ``review`` state right after a ``tool.detected``
                    # ("running") emission on a tool-call-first response.
                    if event is None:
                        schedule_emit_pet_event(
                            "query.first_token",
                            text="Replying",
                            **meta,
                        )
                        last_event = "query.first_token"

                yield result

                if is_last:
                    last_event = None

            await asyncio.to_thread(
                emit_pet_event,
                "query.done",
                text="Done",
                **meta,
            )

        except asyncio.CancelledError:
            schedule_emit_pet_event(
                "query.cancelled",
                text="Interrupted",
                duration_ms=1200,
                **meta,
            )
            raise
        except Exception as exc:
            schedule_emit_pet_event(
                "query.error",
                text=type(exc).__name__,
                duration_ms=2500,
                **meta,
            )
            raise

    AgentRunner.query_handler = patched_query_handler
    _PATCHED = True
    logger.info("QwenPaw Pet patched AgentRunner.query_handler")


def restore_agent_runner() -> None:
    """Restore the original query handler."""
    global _PATCHED

    if not _PATCHED or _ORIGINAL_QUERY_HANDLER is None:
        return

    from qwenpaw.app.runner.runner import AgentRunner

    AgentRunner.query_handler = _ORIGINAL_QUERY_HANDLER
    _PATCHED = False
    logger.info("QwenPaw Pet restored AgentRunner.query_handler")

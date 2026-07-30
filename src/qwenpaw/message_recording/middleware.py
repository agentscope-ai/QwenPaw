# -*- coding: utf-8 -*-
"""Message recording middleware for AgentScope 2.0 on_model_call."""

import inspect
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from agentscope.message import (
    Msg,
    DataBlock,
    HintBlock,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from agentscope.middleware import MiddlewareBase

from ..app.agent_context import (
    get_current_agent_id,
    get_current_session_id,
)
from .buffer import _MessageEvent
from .manager import get_message_recording_manager

if TYPE_CHECKING:
    from agentscope.agent import Agent

logger = logging.getLogger(__name__)


class MessageRecordingMiddleware(MiddlewareBase):
    """Record full LLM I/O to local JSONL via on_model_call hook."""

    def __init__(
        self,
        provider_id: str,
        model_name: str,
        max_content_length: int | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._model_name = model_name
        self._max_length = max_content_length

    async def on_model_call(  # pylint: disable=no-else-return
        self,
        agent: "Agent",  # pylint: disable=unused-argument
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> Any:
        """Intercept model call to record input/output."""
        start_time = time.monotonic()
        result = await next_handler(**input_kwargs)

        if inspect.isasyncgen(result):

            async def _wrap():
                async for chunk in result:
                    if chunk.is_last:
                        self._record(
                            input_kwargs,
                            chunk,
                            start_time,
                        )
                    yield chunk

            return _wrap()
        else:
            self._record(input_kwargs, result, start_time)
            return result

    def _record(  # pylint: disable=too-many-locals
        self,
        input_kwargs: dict[str, Any],
        response: Any,
        start_time: float,
    ) -> None:
        """Serialize and enqueue the recording event."""
        try:
            mgr = get_message_recording_manager()

            duration_ms = int(
                (time.monotonic() - start_time) * 1000,
            )

            messages = input_kwargs.get("messages") or []
            serialized_msgs = [
                _serialize_msg(m, self._max_length)
                for m in messages
                if isinstance(m, Msg)
            ]

            tools = input_kwargs.get("tools") or []
            tool_choice = input_kwargs.get("tool_choice")

            serialized_resp = _serialize_response(
                response,
                self._max_length,
            )

            session_id = get_current_session_id() or ""
            agent_id = get_current_agent_id()

            request_id = str(
                getattr(response, "id", "") or "",
            )

            event = _MessageEvent(
                timestamp=datetime.now(
                    tz=timezone.utc,
                ).isoformat(timespec="milliseconds"),
                request_id=request_id,
                session_id=session_id,
                agent_id=agent_id,
                provider_id=self._provider_id,
                model_name=self._model_name,
                messages=serialized_msgs,
                tools=tools,
                tool_choice=tool_choice,
                response=serialized_resp,
                duration_ms=duration_ms,
            )
            mgr.enqueue(event)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug(
                "message_recording: _record failed",
                exc_info=True,
            )


def _serialize_msg(
    msg: Msg,
    max_length: int | None,
) -> dict[str, Any]:
    """Convert an AgentScope Msg to a serializable dict."""
    result: dict[str, Any] = {
        "role": msg.role,
    }
    if msg.name:
        result["name"] = msg.name

    content_blocks = []
    for block in msg.content or []:
        content_blocks.append(
            _serialize_block(block, max_length),
        )
    result["content"] = content_blocks
    return result


# pylint: disable=too-many-return-statements,no-else-return
def _serialize_block(
    block: Any,
    max_length: int | None,
) -> dict[str, Any]:
    """Serialize a single content block."""
    if isinstance(block, TextBlock):
        return {
            "type": "text",
            "text": _truncate_text(
                block.text,
                max_length,
            ),
        }
    elif isinstance(block, ThinkingBlock):
        return {
            "type": "thinking",
            "thinking": _truncate_text(
                block.thinking,
                max_length,
            ),
        }
    elif isinstance(block, ToolCallBlock):
        return {
            "type": "tool_call",
            "id": block.id,
            "name": block.name,
            "input": _truncate_text(
                block.input,
                max_length,
            ),
        }
    elif isinstance(block, ToolResultBlock):
        output = block.output
        if isinstance(output, str):
            output_serialized = _truncate_text(
                output,
                max_length,
            )
        elif isinstance(output, list):
            output_serialized = [
                _serialize_block(b, max_length) for b in output
            ]
        else:
            output_serialized = str(output)
        return {
            "type": "tool_result",
            "id": block.id,
            "name": block.name,
            "output": output_serialized,
        }
    elif isinstance(block, DataBlock):
        media_type = ""
        if hasattr(block, "source") and block.source:
            media_type = getattr(
                block.source,
                "media_type",
                "",
            )
        return {
            "type": "data",
            "media_type": media_type,
            "_omitted": True,
        }
    elif isinstance(block, HintBlock):
        hint = block.hint
        if isinstance(hint, str):
            return {
                "type": "hint",
                "hint": _truncate_text(hint, max_length),
            }
        return {
            "type": "hint",
            "hint": [_serialize_block(b, max_length) for b in hint],
        }
    else:
        return {"type": "unknown", "_raw": str(block)[:200]}


def _serialize_response(
    response: Any,
    max_length: int | None,
) -> dict[str, Any]:
    """Serialize ChatResponse to a dict."""
    result: dict[str, Any] = {}

    content = getattr(response, "content", None)
    if isinstance(content, list):
        result["content"] = [_serialize_block(b, max_length) for b in content]

    usage = getattr(response, "usage", None)
    if usage is not None:
        result["usage"] = {
            "input_tokens": getattr(
                usage,
                "input_tokens",
                0,
            ),
            "output_tokens": getattr(
                usage,
                "output_tokens",
                0,
            ),
        }

    return result


def _truncate_text(
    text: str,
    max_length: int | None,
) -> str:
    """Truncate text if it exceeds max_length."""
    if max_length is None or not isinstance(text, str):
        return text
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}[truncated]"

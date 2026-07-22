# -*- coding: utf-8 -*-
"""Convert QwenPaw events to AG-UI protocol format.

This module provides event conversion logic, adapting QwenPaw's
custom event format to AG-UI protocol event format.

QwenPaw uses its own event system (response → message → content),
not standard AgentScope AgentEvent hierarchy.
"""
import json
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from ag_ui.core.events import BaseEvent as AGUIBaseEvent
else:
    AGUIBaseEvent = Any

try:
    from ag_ui.core.events import (
        CustomEvent as AGUICustomEvent,
        ReasoningMessageContentEvent as AGUIReasoningMessageContentEvent,
        ReasoningMessageEndEvent as AGUIReasoningMessageEndEvent,
        ReasoningMessageStartEvent as AGUIReasoningMessageStartEvent,
        RunErrorEvent as AGUIRunErrorEvent,
        RunFinishedEvent as AGUIRunFinishedEvent,
        RunStartedEvent as AGUIRunStartedEvent,
        TextMessageContentEvent as AGUITextMessageContentEvent,
        TextMessageEndEvent as AGUITextMessageEndEvent,
        TextMessageStartEvent as AGUITextMessageStartEvent,
        ToolCallArgsEvent as AGUIToolCallArgsEvent,
        ToolCallEndEvent as AGUIToolCallEndEvent,
        ToolCallResultEvent as AGUIToolCallResultEvent,
        ToolCallStartEvent as AGUIToolCallStartEvent,
    )
    AG_UI_AVAILABLE = True
except ImportError:
    AG_UI_AVAILABLE = False


class QwenPawToAGUIConverter:
    """Convert QwenPaw events to AG-UI protocol format.

    Handles QwenPaw's custom event format: response → message → content.
    Create one instance per request (via :func:`create_converter`) to keep
    per-run state isolated across concurrent streams.
    """

    def __init__(self) -> None:
        """Initialize the converter."""
        if not AG_UI_AVAILABLE:
            raise ImportError(
                "ag-ui-protocol is required for AG-UI support. "
                "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'"
            )
        # Per-run state (instance is request-scoped, so this is concurrency-safe)
        self._run_id: str = ""
        # Tracks whether the current open message is reasoning or text, so that
        # nested content deltas can be routed to the correct message type.
        self._current_message_type: str = ""

    def convert(self, event: Any) -> dict:
        """Convert a QwenPaw event to AG-UI protocol dict.

        Args:
            event: The QwenPaw event to convert (can be dict or object)

        Returns:
            Dictionary in AG-UI protocol format.
        """
        # Handle both dict and object events
        if isinstance(event, dict):
            event_dict = event
        else:
            # Try to get dict representation
            if hasattr(event, "model_dump"):
                event_dict = event.model_dump(exclude_none=True)
            elif hasattr(event, "dict"):
                event_dict = event.dict()
            else:
                # Fallback to unknown
                event_dict = {
                    "raw_type": str(type(event)),
                    "raw_data": str(event),
                }

        # Convert based on event structure
        agui_event = self._to_agui_event(event_dict)
        return agui_event.model_dump(
            mode="json",
            exclude_none=True,
            by_alias=True,
        )

    def _to_agui_event(self, event: Dict[str, Any]) -> "AGUIBaseEvent":
        """Convert a QwenPaw event dict to an AG-UI event object.

        This method handles QwenPaw's custom event format:
        - Response events → RunStarted/RunFinished
        - Message events → MessageStart/MessageEnd
        - Content events → MessageContent
        - Tool events → ToolCallStart/Args/End/Result
        """
        # Check for response events (highest level)
        if event.get("object") == "response":
            status = event.get("status")
            if status == "created":
                self._run_id = event.get("id", "")
                return AGUIRunStartedEvent(
                    thread_id=event.get("session_id", ""),
                    run_id=self._run_id,
                )
            elif status == "completed":
                return AGUIRunFinishedEvent(
                    thread_id=event.get("session_id", ""),
                    run_id=self._run_id,
                )
            # In-progress or other states, emit as custom
            return AGUICustomEvent(
                name="response_status",
                value=event,
            )

        # Check for message events
        if event.get("object") == "message":
            msg_type = event.get("type", "")
            msg_id = event.get("id", "")
            status = event.get("status", "")

            if msg_type == "reasoning":
                if status == "in_progress":
                    self._current_message_type = "reasoning"
                    return AGUIReasoningMessageStartEvent(
                        message_id=msg_id,
                        role="reasoning",  # AG-UI spec requires literal "reasoning"
                    )
                if status == "completed":
                    self._current_message_type = ""
                    return AGUIReasoningMessageEndEvent(
                        message_id=msg_id,
                    )

            elif msg_type in ("text", "message"):
                # Treat type="message" (assistant messages) as text messages
                if status == "in_progress":
                    self._current_message_type = "text"
                    return AGUITextMessageStartEvent(
                        message_id=msg_id,
                    )
                if status == "completed":
                    self._current_message_type = ""
                    return AGUITextMessageEndEvent(
                        message_id=msg_id,
                    )

            # Fallback for other message types
            return AGUICustomEvent(
                name="message_unknown",
                value=event,
            )

        # Check for content events (nested inside messages)
        if event.get("object") == "content":
            content_type = event.get("type", "")
            msg_id = event.get("msg_id", "")
            text = event.get("text", "")

            if content_type == "text" and text:
                # Route content delta based on the currently open message type
                if self._current_message_type == "reasoning":
                    return AGUIReasoningMessageContentEvent(
                        message_id=msg_id,
                        delta=text,
                    )
                return AGUITextMessageContentEvent(
                    message_id=msg_id,
                    delta=text,
                )

            # Fallback for other content types
            return AGUICustomEvent(
                name="content_unknown",
                value=event,
            )

        # Check for tool events
        if event.get("object") == "tool_call":
            tool_call_id = event.get("id", "")
            tool_name = event.get("name", "")
            status = event.get("status", "")

            if status == "created":
                return AGUIToolCallStartEvent(
                    tool_call_id=tool_call_id,
                    tool_call_name=tool_name,
                    parent_message_id=self._run_id,
                )
            if status == "completed":
                return AGUIToolCallEndEvent(
                    tool_call_id=tool_call_id,
                )

            # In-progress tool call: stream arguments as TOOL_CALL_ARGS deltas
            # so clients can reconstruct the tool input (AG-UI spec requires it).
            args_delta = self._extract_tool_args_delta(event)
            if args_delta is not None:
                return AGUIToolCallArgsEvent(
                    tool_call_id=tool_call_id,
                    delta=args_delta,
                )

            return AGUICustomEvent(
                name="tool_call_info",
                value=event,
            )

        # Check for tool result events
        if event.get("object") == "tool_result":
            tool_call_id = event.get("tool_call_id", "")
            content = event.get("content", "")
            status = event.get("status", "")

            if status == "success":
                return AGUIToolCallResultEvent(
                    tool_call_id=tool_call_id,
                    message_id=self._run_id,
                    content=self._stringify_tool_content(content),
                )

            return AGUICustomEvent(
                name="tool_result_status",
                value=event,
            )

        # Fallback for unknown event types
        return AGUICustomEvent(
            name="unknown",
            value=event,
        )

    @staticmethod
    def _extract_tool_args_delta(event: Dict[str, Any]) -> str | None:
        """Extract a tool-call arguments delta from a QwenPaw tool event.

        QwenPaw may carry tool input in ``arguments``/``input``/``args``
        (either a string fragment or a JSON-serializable object). Returns the
        serialized delta, or None if no arguments are present.
        """
        for key in ("arguments", "input", "args"):
            value = event.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                return value
            return json.dumps(value, ensure_ascii=False)
        return None

    @staticmethod
    def _stringify_tool_content(content: Any) -> str:
        """Coerce a tool result content value to a string for AG-UI.

        AG-UI ToolCallResultEvent.content must be a str; QwenPaw may emit
        dict/list/None payloads.
        """
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False)


def create_converter() -> QwenPawToAGUIConverter:
    """创建新的转换器实例.

    用于每个请求创建独立的转换器，避免并发状态冲突。

    Returns:
        新的转换器实例

    Raises:
        ImportError: 如果 ag-ui-protocol 未安装
    """
    return QwenPawToAGUIConverter()


def create_run_error_event(message: str, code: str | None = None) -> dict:
    """构造一个符合 AG-UI 规范的 RUN_ERROR 事件字典.

    用于在流式过程中发生异常时向客户端发送标准错误事件，
    而非非规范的 ``{"type": "error"}``。

    Args:
        message: 错误描述
        code: 可选的错误代码

    Returns:
        AG-UI RUN_ERROR 事件字典（已序列化、camelCase 别名）

    Raises:
        ImportError: 如果 ag-ui-protocol 未安装
    """
    if not AG_UI_AVAILABLE:
        raise ImportError(
            "ag-ui-protocol is required for AG-UI support. "
            "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'"
        )
    kwargs: Dict[str, Any] = {"message": message}
    if code:
        kwargs["code"] = code
    event = AGUIRunErrorEvent(**kwargs)
    return event.model_dump(mode="json", exclude_none=True, by_alias=True)

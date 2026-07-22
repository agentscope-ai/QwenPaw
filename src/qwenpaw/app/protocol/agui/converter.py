# -*- coding: utf-8 -*-
"""Convert QwenPaw events to AG-UI protocol format.

This module provides event conversion logic, adapting QwenPaw's
custom event format to AG-UI protocol event format.

QwenPaw uses its own event system (response → message → content),
not standard AgentScope AgentEvent hierarchy.
"""
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
        RunFinishedEvent as AGUIRunFinishedEvent,
        RunStartedEvent as AGUIRunStartedEvent,
        TextMessageContentEvent as AGUITextMessageContentEvent,
        TextMessageEndEvent as AGUITextMessageEndEvent,
        TextMessageStartEvent as AGUITextMessageStartEvent,
        ToolCallStartEvent as AGUIToolCallStartEvent,
        ToolCallEndEvent as AGUIToolCallEndEvent,
        ToolCallResultEvent as AGUIToolCallResultEvent,
    )
    AG_UI_AVAILABLE = True
except ImportError:
    AG_UI_AVAILABLE = False


class QwenPawToAGUIConverter:
    """Convert QwenPaw events to AG-UI protocol format.

    Handles QwenPaw's custom event format: response → message → content.
    """

    def __init__(self) -> None:
        """Initialize the converter."""
        if not AG_UI_AVAILABLE:
            raise ImportError(
                "ag-ui-protocol is required for AG-UI support. "
                "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'"
            )
        # State tracking
        self._run_id: str = ""
        self._current_message_id: str = ""
        self._current_message_type: str = ""  # "text" or "reasoning"
        self._last_model_name: str = "model"
        self._tool_result_buffers: dict[str, list[str]] = {}

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
            if hasattr(event, 'model_dump'):
                event_dict = event.model_dump(exclude_none=True)
            elif hasattr(event, 'dict'):
                event_dict = event.dict()
            else:
                # Fallback to unknown
                event_dict = {"raw_type": str(type(event)), "raw_data": str(event)}

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
        - Tool events → ToolCallStart/ToolCallEnd/ToolCallResult
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
            else:
                # In-progress or other states, emit as custom
                return AGUICustomEvent(
                    name="response_status",
                    value=event,
                )

        # Check for message events
        elif event.get("object") == "message":
            msg_type = event.get("type", "")
            msg_id = event.get("id", "")
            status = event.get("status", "")

            if msg_type == "reasoning":
                if status == "in_progress":
                    self._current_message_id = msg_id
                    self._current_message_type = "reasoning"
                    return AGUIReasoningMessageStartEvent(
                        message_id=msg_id,
                        role="reasoning",  # AG-UI spec requires literal "reasoning"
                    )
                elif status == "completed":
                    self._current_message_type = ""
                    return AGUIReasoningMessageEndEvent(
                        message_id=msg_id,
                    )

            elif msg_type in ("text", "message"):
                # Treat type="message" (assistant messages) as text messages
                if status == "in_progress":
                    self._current_message_id = msg_id
                    self._current_message_type = "text"
                    return AGUITextMessageStartEvent(
                        message_id=msg_id,
                    )
                elif status == "completed":
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
        elif event.get("object") == "content":
            content_type = event.get("type", "")
            msg_id = event.get("msg_id", "")
            delta = event.get("delta", False)
            text = event.get("text", "")

            if content_type == "text" and text:
                # Use current message type to decide reasoning vs text content
                if self._current_message_type == "reasoning":
                    return AGUIReasoningMessageContentEvent(
                        message_id=msg_id,
                        delta=text,
                    )
                else:
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
        elif event.get("object") == "tool_call":
            tool_call_id = event.get("id", "")
            tool_name = event.get("name", "")
            status = event.get("status", "")

            if status == "created":
                return AGUIToolCallStartEvent(
                    tool_call_id=tool_call_id,
                    tool_call_name=tool_name,
                    parent_message_id=self._run_id,
                )
            elif status == "completed":
                return AGUIToolCallEndEvent(
                    tool_call_id=tool_call_id,
                )

            # Tool arguments (would be separate events)
            return AGUICustomEvent(
                name="tool_call_info",
                value=event,
            )

        # Check for tool result events
        elif event.get("object") == "tool_result":
            tool_call_id = event.get("tool_call_id", "")
            content = event.get("content", "")
            status = event.get("status", "")

            if status == "success":
                return AGUIToolCallResultEvent(
                    tool_call_id=tool_call_id,
                    message_id=self._run_id,
                    content=content,
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


# Create global converter instance
_converter_instance: QwenPawToAGUIConverter | None = None


def get_converter() -> QwenPawToAGUIConverter:
    """获取或创建全局转换器实例.

    Returns:
        全局转换器实例

    Raises:
        ImportError: 如果 ag-ui-protocol 未安装
    """
    global _converter_instance
    if _converter_instance is None:
        _converter_instance = QwenPawToAGUIConverter()
    return _converter_instance


def convert_agent_event_to_agui(event: Any) -> dict:
    """将 QwenPaw 事件转换为 AG-UI 协议格式.

    注意：此函数使用全局单例转换器，在并发请求中可能产生竞态条件。
    建议在需要高并发场景时为每个请求创建独立的转换器实例。

    Args:
        event: 要转换的 QwenPaw 事件

    Returns:
        AG-UI 协议格式的字典

    Raises:
        ImportError: 如果 ag-ui-protocol 未安装
    """
    converter = get_converter()
    return converter.convert(event)


def create_converter() -> QwenPawToAGUIConverter:
    """创建新的转换器实例.

    用于每个请求创建独立的转换器，避免并发状态冲突。

    Returns:
        新的转换器实例

    Raises:
        ImportError: 如果 ag-ui-protocol 未安装
    """
    return QwenPawToAGUIConverter()

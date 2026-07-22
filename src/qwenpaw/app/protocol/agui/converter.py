# -*- coding: utf-8 -*-
"""QwenPaw runtime-envelope → AG-UI protocol event converter."""

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
    """Convert runtime envelope events into AG-UI protocol events.

    QwenPaw's runtime emits nested ``response → message → content``
    envelopes, where tool calls are ``object="message"`` entries with
    content blocks whose ``data`` is a ``FunctionCall`` or
    ``FunctionCallOutput`` dict.

    Create one instance per request via :func:`create_converter` so
    per-run state stays isolated across concurrent streams.
    """

    def __init__(self) -> None:
        if not AG_UI_AVAILABLE:
            raise ImportError(
                "ag-ui-protocol is required for AG-UI support. "
                "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'",
            )
        self._run_id: str = ""
        # Tracks whether the current open message is reasoning or text so
        # nested ``content`` deltas are routed to the right message type.
        self._msg_type: str = ""
        # msg_ids that have already emitted streaming (delta=True) content
        # chunks.  The final, non-delta chunk is skipped to avoid
        # duplicating the full text after every streaming block.
        self._streamed_msg_ids: set[str] = set()

    # -- public API ----------------------------------------------------------

    def convert(self, event: Any) -> dict:
        """Convert a runtime envelope event to an AG-UI event dict."""
        if isinstance(event, dict):
            ev = event
        elif hasattr(event, "model_dump"):
            ev = event.model_dump(exclude_none=True)
        elif hasattr(event, "dict"):
            ev = event.dict()
        else:
            ev = {"raw_type": str(type(event)), "raw_data": str(event)}
        agui = self._to_agui_event(ev)
        return agui.model_dump(mode="json", exclude_none=True, by_alias=True)

    # -- conversion ----------------------------------------------------------

    def _to_agui_event(
        self, ev: Dict[str, Any]
    ) -> "AGUIBaseEvent":  # noqa: C901,E501
        obj = ev.get("object", "")

        # ---- response ------------------------------------------------------
        if obj == "response":
            return self._handle_response(ev)

        # ---- message -------------------------------------------------------
        if obj == "message":
            return self._handle_message(ev)

        # ---- content -------------------------------------------------------
        if obj == "content":
            return self._handle_content(ev)

        return AGUICustomEvent(name="unknown", value=ev)

    # -- helpers ------------------------------------------------------------

    def _handle_response(self, ev: Dict[str, Any]) -> "AGUIBaseEvent":
        status = ev.get("status")
        if status == "created":
            self._run_id = ev.get("id", "")
            return AGUIRunStartedEvent(
                thread_id=ev.get("session_id", ""),
                run_id=self._run_id,
            )
        if status == "completed":
            return AGUIRunFinishedEvent(
                thread_id=ev.get("session_id", ""),
                run_id=self._run_id,
            )
        return AGUICustomEvent(name="response_status", value=ev)

    def _handle_message(self, ev: Dict[str, Any]) -> "AGUIBaseEvent":
        msg_type = ev.get("type", "")
        msg_id = ev.get("id", "")
        status = ev.get("status", "")
        content = ev.get("content") or []

        # --- plugin call (tool call) ---------------------------------------
        if self._has_plugin_call(content):
            return self._handle_tool_message(ev, msg_id, status)

        # --- plugin output (tool result) -----------------------------------
        if self._has_plugin_output(content):
            return self._handle_tool_result(ev, msg_id)

        # --- reasoning ------------------------------------------------------
        if msg_type == "reasoning":
            return self._handle_reasoning(ev, msg_id, status)

        # --- text / assistant -----------------------------------------------
        if msg_type in ("text", "message"):
            return self._handle_text(ev, msg_id, status)

        return AGUICustomEvent(name="message_unknown", value=ev)

    def _handle_content(self, ev: Dict[str, Any]) -> "AGUIBaseEvent":
        ctype = ev.get("type", "")
        msg_id = ev.get("msg_id", "")
        text = ev.get("text", "")
        delta = ev.get("delta", False)

        # --- data content (tool call delta / tool result) -------------------
        if ctype == "data":
            return self._handle_data_content(ev, msg_id)

        # --- text content ---------------------------------------------------
        if ctype == "text" and text:
            return self._handle_text_content(msg_id, text, delta)

        return AGUICustomEvent(name="content_unknown", value=ev)

    # -- tool events (real envelope format) ----------------------------------

    @staticmethod
    def _has_plugin_call(content: list) -> bool:
        for block in content:
            data = block.get("data") if isinstance(block, dict) else None
            if isinstance(data, dict) and data.get("name"):
                return True
        return False

    @staticmethod
    def _has_plugin_output(content: list) -> bool:
        for block in content:
            data = block.get("data") if isinstance(block, dict) else None
            if isinstance(data, dict) and "output" in data:
                return True
        return False

    def _handle_tool_message(
        self,
        ev: Dict[str, Any],
        msg_id: str,
        status: str,
    ) -> "AGUIBaseEvent":
        content = ev.get("content") or []
        tool_name = ""
        for block in content:
            data = block.get("data") if isinstance(block, dict) else {}
            if isinstance(data, dict) and data.get("name"):
                tool_name = data["name"]
                break

        if status == "in_progress":
            return AGUIToolCallStartEvent(
                tool_call_id=msg_id,
                tool_call_name=tool_name,
                parent_message_id=self._run_id,
            )
        if status == "completed":
            return AGUIToolCallEndEvent(tool_call_id=msg_id)
        return AGUICustomEvent(name="tool_call_info", value=ev)

    def _handle_tool_result(
        self,
        ev: Dict[str, Any],
        msg_id: str,
    ) -> "AGUIBaseEvent":  # noqa: E501
        result = None
        for block in ev.get("content") or []:
            data = block.get("data") if isinstance(block, dict) else {}
            if isinstance(data, dict) and "output" in data:
                result = data
                break

        if result:
            output = result.get("output")
            if output is None:
                output = result.get("text", "")
            output_str = (
                output
                if isinstance(output, str)
                else json.dumps(output, ensure_ascii=False)
            )
            return AGUIToolCallResultEvent(
                tool_call_id=msg_id,
                message_id=self._run_id,
                content=output_str,
            )

        return AGUICustomEvent(
            name="tool_result_status",
            value=ev,
        )

    def _handle_data_content(
        self,
        ev: Dict[str, Any],
        msg_id: str,
    ) -> "AGUIBaseEvent":  # noqa: E501
        data = ev.get("data")
        if not isinstance(data, dict):
            return AGUICustomEvent(name="content_data", value=ev)

        # Tool-call argument deltas
        if data.get("name"):
            return AGUIToolCallArgsEvent(
                tool_call_id=msg_id,
                delta=json.dumps(data, ensure_ascii=False),
            )

        # Tool result deltas
        if "output" in data:
            output = data.get("output")
            if output is None:
                output = data.get("text", "")
            output_str = (
                output
                if isinstance(output, str)
                else json.dumps(output, ensure_ascii=False)
            )
            return AGUIToolCallResultEvent(
                tool_call_id=msg_id,
                message_id=self._run_id,
                content=output_str,
            )

        return AGUICustomEvent(name="content_data", value=ev)

    # -- message types -------------------------------------------------------

    def _handle_reasoning(
        self,
        ev: Dict[str, Any],
        msg_id: str,
        status: str,
    ) -> "AGUIBaseEvent":
        if status == "in_progress":
            self._msg_type = "reasoning"
            return AGUIReasoningMessageStartEvent(
                message_id=msg_id,
                role="reasoning",
            )
        if status == "completed":
            self._msg_type = ""
            return AGUIReasoningMessageEndEvent(message_id=msg_id)
        return AGUICustomEvent(name="reasoning_status", value=ev)

    def _handle_text(
        self,
        ev: Dict[str, Any],
        msg_id: str,
        status: str,
    ) -> "AGUIBaseEvent":
        if status == "in_progress":
            self._msg_type = "text"
            return AGUITextMessageStartEvent(message_id=msg_id)
        if status == "completed":
            self._msg_type = ""
            return AGUITextMessageEndEvent(message_id=msg_id)
        return AGUICustomEvent(name="text_status", value=ev)

    def _handle_text_content(
        self,
        msg_id: str,
        text: str,
        delta: bool,
    ) -> "AGUIBaseEvent":
        # Skip final non-delta (full-replay) chunks when we already streamed
        # deltas — avoids duplicating accumulated text at end of each block.
        if not delta and msg_id in self._streamed_msg_ids:
            return AGUICustomEvent(
                name="content_suppressed",
                value={"msg_id": msg_id, "reason": "duplicate final chunk"},
            )

        if delta:
            self._streamed_msg_ids.add(msg_id)

        if self._msg_type == "reasoning":
            return AGUIReasoningMessageContentEvent(
                message_id=msg_id,
                delta=text,
            )
        return AGUITextMessageContentEvent(
            message_id=msg_id,
            delta=text,
        )


# -- public helpers ----------------------------------------------------------


def create_converter() -> QwenPawToAGUIConverter:
    """Return a new, per-request converter instance."""
    return QwenPawToAGUIConverter()


def create_run_error_event(message: str, code: str | None = None) -> dict:
    """Build a spec-compliant ``RUN_ERROR`` event dict."""
    if not AG_UI_AVAILABLE:
        raise ImportError(
            "ag-ui-protocol is required for AG-UI support. "
            "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'",
        )
    kwargs: Dict[str, Any] = {"message": message}
    if code:
        kwargs["code"] = code
    return AGUIRunErrorEvent(**kwargs).model_dump(
        mode="json",
        exclude_none=True,
        by_alias=True,
    )

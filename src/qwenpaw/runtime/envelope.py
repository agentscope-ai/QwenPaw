# -*- coding: utf-8 -*-
"""SSE envelope state machine.

Translates agentscope ``EventType`` events into the frontend's
streaming envelope protocol.  Tracks per-request state (text blocks,
reasoning blocks, tool calls) and emits the correct event sequence
that ``Builder.tsx`` expects.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict

from .message_convert import _media_type_to_block_type

logger = logging.getLogger(__name__)


class Envelope:
    """SSE envelope generation + state machine.

    One instance per ``Runtime.run()`` invocation.  Methods are async
    generators that yield schema objects (``AgentResponse``, ``Message``,
    ``TextContent``, ``DataContent``) identical to what the legacy
    ``stream_query`` produced.
    """

    def __init__(self, session_id: str = "") -> None:
        from ..schemas import (
            AgentResponse,
            Message,
            MessageType,
            Role,
            RunStatus,
        )

        self._response = AgentResponse(output=[], status=RunStatus.Created)
        self._response.object = "response"
        self._response.session_id = session_id

        self._message_id = uuid.uuid4().hex
        self._completed_message = Message(
            id=self._message_id,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[],
            status=RunStatus.InProgress,
        )
        self._completed_message.name = "assistant"
        self._completed_message.object = "message"
        self._message_started = False

        self._text_blocks: Dict[str, Dict[str, Any]] = {}
        self._reasoning_blocks: Dict[str, Dict[str, Any]] = {}
        self._tool_calls: Dict[str, Dict[str, Any]] = {}

        self._error_text: str | None = None
        self._finalized = False

    # ------------------------------------------------------------------
    # Response lifecycle
    # ------------------------------------------------------------------

    async def emit_response_created(self) -> AsyncGenerator[Any, None]:
        from ..schemas import RunStatus

        self._response.status = RunStatus.Created
        yield self._response
        self._response.status = RunStatus.InProgress
        yield self._response

    # ------------------------------------------------------------------
    # Event translation
    # ------------------------------------------------------------------

    # pylint: disable=too-many-branches,too-many-statements
    async def translate_event(  # noqa: C901, PLR0912
        self,
        event: Any,
    ) -> AsyncGenerator[Any, None]:
        """Translate one agentscope ``EventType`` event
        into 0..N envelope objects.
        """
        from agentscope.event import EventType
        from ..schemas import (
            ContentType,
            DataContent,
            Message,
            MessageType,
            Role,
            RunStatus,
            TextContent,
        )

        evt_type = getattr(event, "type", None)
        if hasattr(evt_type, "value"):
            evt_type = evt_type.value

        # === TEXT BLOCK ===
        if evt_type == EventType.TEXT_BLOCK_START.value:
            if not self._message_started:
                yield self._completed_message
                self._message_started = True
            block_id = event.block_id
            index = len(self._text_blocks)
            self._text_blocks[block_id] = {"index": index, "text": ""}

        elif evt_type == EventType.TEXT_BLOCK_DELTA.value:
            if not self._message_started:
                yield self._completed_message
                self._message_started = True
            block_id = event.block_id
            delta = event.delta or ""
            state = self._text_blocks.setdefault(
                block_id,
                {"index": len(self._text_blocks), "text": ""},
            )
            state["text"] += delta
            chunk = TextContent(
                type=ContentType.TEXT,
                text=delta,
                delta=True,
                index=state["index"],
            )
            chunk.msg_id = self._message_id
            chunk.object = "content"
            yield chunk

        elif evt_type == EventType.TEXT_BLOCK_END.value:
            block_id = event.block_id
            state = self._text_blocks.get(block_id)
            if state is None:
                return
            final_chunk = TextContent(
                type=ContentType.TEXT,
                text=state["text"],
                delta=False,
                index=state["index"],
            )
            final_chunk.msg_id = self._message_id
            final_chunk.object = "content"
            yield final_chunk
            self._completed_message.content.append(
                TextContent(
                    type=ContentType.TEXT,
                    text=state["text"],
                    delta=False,
                    index=state["index"],
                ),
            )

        # === THINKING BLOCK ===
        elif evt_type == EventType.THINKING_BLOCK_START.value:
            block_id = event.block_id
            r_msg_id = uuid.uuid4().hex
            r_envelope = Message(
                id=r_msg_id,
                type=MessageType.REASONING,
                role=Role.ASSISTANT,
                content=[],
                status=RunStatus.InProgress,
            )
            r_envelope.name = "assistant"
            r_envelope.object = "message"
            self._reasoning_blocks[block_id] = {
                "msg_id": r_msg_id,
                "envelope": r_envelope,
                "text": "",
            }
            yield r_envelope

        elif evt_type == EventType.THINKING_BLOCK_DELTA.value:
            block_id = event.block_id
            delta = getattr(event, "delta", "") or ""
            state = self._reasoning_blocks.get(block_id)
            if state is None:
                r_msg_id = uuid.uuid4().hex
                r_envelope = Message(
                    id=r_msg_id,
                    type=MessageType.REASONING,
                    role=Role.ASSISTANT,
                    content=[],
                    status=RunStatus.InProgress,
                )
                r_envelope.name = "assistant"
                r_envelope.object = "message"
                state = {
                    "msg_id": r_msg_id,
                    "envelope": r_envelope,
                    "text": "",
                }
                self._reasoning_blocks[block_id] = state
                yield r_envelope
            state["text"] += delta
            r_chunk = TextContent(
                type=ContentType.TEXT,
                text=delta,
                delta=True,
                index=0,
            )
            r_chunk.msg_id = state["msg_id"]
            r_chunk.object = "content"
            yield r_chunk

        elif evt_type == EventType.THINKING_BLOCK_END.value:
            block_id = event.block_id
            state = self._reasoning_blocks.get(block_id)
            if state is None:
                return
            r_final = TextContent(
                type=ContentType.TEXT,
                text=state["text"],
                delta=False,
                index=0,
            )
            r_final.msg_id = state["msg_id"]
            r_final.object = "content"
            yield r_final
            state["envelope"].content.append(
                TextContent(
                    type=ContentType.TEXT,
                    text=state["text"],
                    delta=False,
                    index=0,
                ),
            )
            state["envelope"].status = RunStatus.Completed
            self._response.output.append(state["envelope"])
            yield state["envelope"]

        # === TOOL CALL ===
        elif evt_type == EventType.TOOL_CALL_START.value:
            self._tool_calls[event.tool_call_id] = {
                "input_msg_id": uuid.uuid4().hex,
                "name": event.tool_call_name,
                "args_json_acc": "",
                "output_text_acc": "",
            }

        elif evt_type == EventType.TOOL_CALL_DELTA.value:
            state = self._tool_calls.get(event.tool_call_id)
            if state is None:
                state = {
                    "input_msg_id": uuid.uuid4().hex,
                    "name": "",
                    "args_json_acc": "",
                    "output_text_acc": "",
                }
                self._tool_calls[event.tool_call_id] = state
            state["args_json_acc"] += event.delta or ""

        elif evt_type == EventType.TOOL_CALL_END.value:
            state = self._tool_calls.get(event.tool_call_id)
            if state is None:
                return
            raw = state["args_json_acc"]
            try:
                parsed_args: Any = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed_args = raw
            in_data = DataContent(
                type=ContentType.DATA,
                data={
                    "name": state["name"],
                    "call_id": event.tool_call_id,
                    "arguments": parsed_args,
                },
            )
            in_envelope = Message(
                id=state["input_msg_id"],
                type=MessageType.PLUGIN_CALL,
                role=Role.ASSISTANT,
                content=[in_data],
                status=RunStatus.Completed,
            )
            in_envelope.name = "assistant"
            in_envelope.object = "message"
            self._response.output.append(in_envelope)
            yield in_envelope

        # === TOOL RESULT ===
        elif evt_type == EventType.TOOL_RESULT_START.value:
            state = self._tool_calls.get(event.tool_call_id)
            if state is None:
                state = {
                    "input_msg_id": uuid.uuid4().hex,
                    "name": event.tool_call_name,
                    "args_json_acc": "",
                    "output_text_acc": "",
                }
                self._tool_calls[event.tool_call_id] = state
            state["output_msg_id"] = uuid.uuid4().hex
            stub_data = DataContent(
                type=ContentType.DATA,
                data={
                    "name": state["name"],
                    "call_id": event.tool_call_id,
                    "output": "",
                },
            )
            out_envelope = Message(
                id=state["output_msg_id"],
                type=MessageType.PLUGIN_CALL_OUTPUT,
                role=Role.ASSISTANT,
                content=[stub_data],
                status=RunStatus.InProgress,
            )
            out_envelope.name = "assistant"
            out_envelope.object = "message"
            state["output_envelope"] = out_envelope
            yield out_envelope

        elif evt_type == EventType.TOOL_RESULT_TEXT_DELTA.value:
            state = self._tool_calls.get(event.tool_call_id)
            if state is not None:
                state["output_text_acc"] += event.delta or ""

        elif evt_type == EventType.TOOL_RESULT_DATA_DELTA.value:
            state = self._tool_calls.get(event.tool_call_id)
            if state is None:
                return
            data_blocks = state.setdefault("output_data_blocks", [])
            media_type = getattr(event, "media_type", None)
            block_type = _media_type_to_block_type(media_type)
            block: dict[str, Any] = {"type": block_type, "source": {}}
            url = getattr(event, "url", None)
            b64 = getattr(event, "data", None)
            if url:
                block["source"] = {
                    "type": "url",
                    "url": url,
                    "media_type": media_type or "",
                }
            elif b64:
                block["source"] = {
                    "type": "base64",
                    "data": b64,
                    "media_type": media_type or "",
                }
            data_blocks.append(block)

        elif evt_type == EventType.TOOL_RESULT_END.value:
            state = self._tool_calls.get(event.tool_call_id)
            if state is None:
                return
            tool_state = getattr(event, "state", None)
            if hasattr(tool_state, "value"):
                tool_state = tool_state.value
            data_blocks = state.get("output_data_blocks")
            if data_blocks:
                output_blocks: list[dict[str, Any]] = list(data_blocks)
                text_acc = state["output_text_acc"]
                if text_acc:
                    output_blocks.append({"type": "text", "text": text_acc})
                tool_output: Any = json.dumps(
                    output_blocks,
                    ensure_ascii=False,
                )
            else:
                tool_output = state["output_text_acc"]
            out_data = DataContent(
                type=ContentType.DATA,
                data={
                    "name": state["name"],
                    "call_id": event.tool_call_id,
                    "output": tool_output,
                    "state": tool_state,
                },
            )
            out_envelope = state.get("output_envelope")
            if out_envelope is None:
                out_envelope = Message(
                    id=uuid.uuid4().hex,
                    type=MessageType.PLUGIN_CALL_OUTPUT,
                    role=Role.ASSISTANT,
                    content=[out_data],
                    status=RunStatus.Completed,
                )
                out_envelope.name = "assistant"
                out_envelope.object = "message"
            else:
                out_envelope.content = [out_data]
                out_envelope.status = RunStatus.Completed
            self._response.output.append(out_envelope)
            yield out_envelope

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def heartbeat(self) -> AsyncGenerator[Any, None]:
        yield self._response

    # ------------------------------------------------------------------
    # Command short-circuit
    # ------------------------------------------------------------------

    async def from_msg(self, cmd_msg: Any) -> AsyncGenerator[Any, None]:
        """Translate a completed ``Msg`` from a slash
        command into a full envelope sequence.
        """
        from ..schemas import ContentType, RunStatus, TextContent

        cmd_text = cmd_msg.get_text_content() or ""

        if not self._message_started:
            yield self._completed_message
            self._message_started = True

        tc = TextContent(
            type=ContentType.TEXT,
            text=cmd_text,
            delta=False,
            index=0,
        )
        tc.msg_id = self._message_id
        tc.object = "content"
        yield tc

        self._completed_message.content.append(tc)
        self._completed_message.status = RunStatus.Completed
        self._completed_message.metadata = (
            getattr(cmd_msg, "metadata", None) or {}
        )
        self._response.output.append(self._completed_message)
        yield self._completed_message

        self._response.status = RunStatus.Completed
        yield self._response
        self._finalized = True

    # ------------------------------------------------------------------
    # Error / Cancel
    # ------------------------------------------------------------------

    async def error_envelope(
        self,
        error_text: str,
    ) -> AsyncGenerator[Any, None]:
        self._error_text = error_text
        async for obj in self._finalize_response():
            yield obj

    async def cancel_envelope(self) -> AsyncGenerator[Any, None]:
        async for obj in self._finalize_response():
            yield obj

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------

    async def finalize(self) -> AsyncGenerator[Any, None]:
        if self._finalized:
            return
        async for obj in self._finalize_response():
            yield obj

    async def _finalize_response(self) -> AsyncGenerator[Any, None]:
        from ..schemas import RunStatus

        if self._finalized:
            return

        if self._message_started:
            self._completed_message.status = RunStatus.Completed
            self._response.output.append(self._completed_message)
            yield self._completed_message

        if self._error_text:
            self._response.status = RunStatus.Failed
            self._response.error = self._error_text
        else:
            self._response.status = RunStatus.Completed
        yield self._response
        self._finalized = True

    @property
    def response(self) -> Any:
        return self._response

    @property
    def agent_ref(self) -> Any:
        """Access point for the agent reference used in session save."""
        return None


__all__ = ["Envelope"]

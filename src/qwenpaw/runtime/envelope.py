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
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict

from .message_convert import _media_type_to_block_type

logger = logging.getLogger(__name__)


def _gen_msg_id() -> str:
    return "msg_" + uuid.uuid4().hex


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
        self._response.id = "response_" + uuid.uuid4().hex
        self._response.created_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        self._response.session_id = session_id

        self._message_id = _gen_msg_id()
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
        self._data_blocks: Dict[str, Dict[str, Any]] = {}

        self._seq_counter = 0

        self._error_text: str | None = None
        self._finalized = False

    # ------------------------------------------------------------------
    # Sequence number helper
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        self._seq_counter += 1
        return self._seq_counter

    def _tag_seq(self, obj: Any) -> Any:
        obj.sequence_number = self._next_seq()
        return obj

    # ------------------------------------------------------------------
    # Response lifecycle
    # ------------------------------------------------------------------

    async def emit_response_created(self) -> AsyncGenerator[Any, None]:
        from ..schemas import RunStatus

        self._response.status = RunStatus.Created
        yield self._tag_seq(self._response)
        self._response.status = RunStatus.InProgress
        yield self._tag_seq(self._response)

    # ------------------------------------------------------------------
    # Text message finalize helper
    # ------------------------------------------------------------------

    def _should_finalize_text_message(self) -> bool:
        return (
            self._message_started and len(self._completed_message.content) > 0
        )

    async def _finalize_text_message(self) -> AsyncGenerator[Any, None]:
        """Finalize the current text message before a tool call starts."""
        from ..schemas import RunStatus

        self._completed_message.status = RunStatus.Completed
        self._response.output.append(self._completed_message)
        yield self._tag_seq(self._completed_message)

        self._message_id = _gen_msg_id()
        from ..schemas import Message, MessageType, Role

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
        self._text_blocks = {}

    # ------------------------------------------------------------------
    # Event translation
    # ------------------------------------------------------------------

    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches,too-many-statements
    async def translate_event(  # noqa: C901, PLR0912, PLR0915
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
            FunctionCall,
            FunctionCallOutput,
            ImageContent,
            AudioContent,
            VideoContent,
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
                yield self._tag_seq(self._completed_message)
                self._message_started = True
            block_id = event.block_id
            index = len(self._text_blocks)
            self._text_blocks[block_id] = {"index": index, "text": ""}

        elif evt_type == EventType.TEXT_BLOCK_DELTA.value:
            if not self._message_started:
                yield self._tag_seq(self._completed_message)
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
            yield self._tag_seq(chunk)

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
            yield self._tag_seq(final_chunk)
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
            r_msg_id = _gen_msg_id()
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
            yield self._tag_seq(r_envelope)

        elif evt_type == EventType.THINKING_BLOCK_DELTA.value:
            block_id = event.block_id
            delta = getattr(event, "delta", "") or ""
            state = self._reasoning_blocks.get(block_id)
            if state is None:
                r_msg_id = _gen_msg_id()
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
                yield self._tag_seq(r_envelope)
            state["text"] += delta
            r_chunk = TextContent(
                type=ContentType.TEXT,
                text=delta,
                delta=True,
                index=0,
            )
            r_chunk.msg_id = state["msg_id"]
            yield self._tag_seq(r_chunk)

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
            yield self._tag_seq(r_final)
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
            yield self._tag_seq(state["envelope"])

        # === TOOL CALL ===
        elif evt_type == EventType.TOOL_CALL_START.value:
            # P0-5: finalize current text message if needed
            if self._should_finalize_text_message():
                async for obj in self._finalize_text_message():
                    yield obj

            call_id = event.tool_call_id
            msg_id = _gen_msg_id()
            plugin_call_message = Message(
                id=msg_id,
                type=MessageType.PLUGIN_CALL,
                role=Role.ASSISTANT,
                content=[],
                status=RunStatus.InProgress,
            )
            plugin_call_message.name = "assistant"
            plugin_call_message.object = "message"

            stub_content = DataContent(
                type=ContentType.DATA,
                data=FunctionCall(
                    call_id=call_id,
                    name=event.tool_call_name,
                    arguments="",
                ).model_dump(),
                delta=False,
                index=0,
            )
            stub_content.msg_id = msg_id

            yield self._tag_seq(plugin_call_message.in_progress())
            yield self._tag_seq(stub_content.in_progress())

            self._tool_calls[call_id] = {
                "name": event.tool_call_name,
                "args_json_acc": "",
                "message": plugin_call_message,
                "output_text_acc": "",
                "output_data_blocks": {},
            }

        elif evt_type == EventType.TOOL_CALL_DELTA.value:
            call_id = event.tool_call_id
            state = self._tool_calls.get(call_id)
            if state is None:
                return
            state["args_json_acc"] += event.delta or ""

            delta_content = DataContent(
                type=ContentType.DATA,
                data=FunctionCall(
                    call_id=call_id,
                    name=state["name"],
                    arguments=state["args_json_acc"],
                ).model_dump(),
                delta=False,
                index=0,
            )
            delta_content.msg_id = state["message"].id
            yield self._tag_seq(delta_content.in_progress())

        elif evt_type == EventType.TOOL_CALL_END.value:
            call_id = event.tool_call_id
            state = self._tool_calls.get(call_id)
            if state is None:
                return

            final_content = DataContent(
                type=ContentType.DATA,
                data=FunctionCall(
                    call_id=call_id,
                    name=state["name"],
                    arguments=state["args_json_acc"],
                ).model_dump(),
                delta=False,
            )
            state["message"].add_content(new_content=final_content)
            yield self._tag_seq(final_content.completed())
            self._response.output.append(state["message"])
            yield self._tag_seq(state["message"].completed())

        # === TOOL RESULT ===
        elif evt_type == EventType.TOOL_RESULT_START.value:
            call_id = event.tool_call_id
            state = self._tool_calls.get(call_id)
            if state is None:
                state = {
                    "name": event.tool_call_name,
                    "args_json_acc": "",
                    "output_text_acc": "",
                    "output_data_blocks": {},
                }
                self._tool_calls[call_id] = state

            out_msg_id = _gen_msg_id()
            out_message = Message(
                id=out_msg_id,
                type=MessageType.PLUGIN_CALL_OUTPUT,
                role=Role.TOOL,
                content=[],
                status=RunStatus.InProgress,
            )
            out_message.name = "assistant"
            out_message.object = "message"

            stub_content = DataContent(
                type=ContentType.DATA,
                data=FunctionCallOutput(
                    call_id=call_id,
                    name=state["name"],
                    output="",
                ).model_dump(),
                delta=False,
                index=0,
            )
            stub_content.msg_id = out_msg_id

            yield self._tag_seq(out_message.in_progress())
            yield self._tag_seq(stub_content.in_progress())

            state["output_message"] = out_message
            state["output_text_acc"] = ""
            state["output_data_blocks"] = {}

        elif evt_type == EventType.TOOL_RESULT_TEXT_DELTA.value:
            call_id = event.tool_call_id
            state = self._tool_calls.get(call_id)
            if state is None:
                return
            state["output_text_acc"] += event.delta or ""

            delta_content = self._build_tool_result_content(
                call_id,
                state,
                ContentType,
                FunctionCallOutput,
            )
            delta_content.msg_id = state["output_message"].id
            yield self._tag_seq(delta_content.in_progress())

        elif evt_type == EventType.TOOL_RESULT_DATA_DELTA.value:
            call_id = event.tool_call_id
            state = self._tool_calls.get(call_id)
            if state is None:
                return

            block_id = event.block_id
            media_type = getattr(event, "media_type", None)
            block_type = _media_type_to_block_type(media_type)

            blocks_dict: dict = state["output_data_blocks"]
            url = getattr(event, "url", None)
            b64 = getattr(event, "data", None)

            if block_id in blocks_dict:
                existing = blocks_dict[block_id]
                if b64:
                    existing["source"]["data"] = (
                        existing["source"].get("data", "") + b64
                    )
            else:
                source: dict[str, Any] = {}
                if url:
                    source = {
                        "type": "url",
                        "url": url,
                        "media_type": media_type or "",
                    }
                elif b64:
                    source = {
                        "type": "base64",
                        "data": b64,
                        "media_type": media_type or "",
                    }
                blocks_dict[block_id] = {
                    "type": block_type,
                    "source": source,
                }

            delta_content = self._build_tool_result_content(
                call_id,
                state,
                ContentType,
                FunctionCallOutput,
            )
            delta_content.msg_id = state["output_message"].id
            yield self._tag_seq(delta_content.in_progress())

        elif evt_type == EventType.TOOL_RESULT_END.value:
            call_id = event.tool_call_id
            state = self._tool_calls.get(call_id)
            if state is None:
                return

            tool_state = getattr(event, "state", None)
            if hasattr(tool_state, "value"):
                tool_state = tool_state.value

            final_content = self._build_tool_result_content(
                call_id,
                state,
                ContentType,
                FunctionCallOutput,
                tool_state=tool_state,
            )

            out_message = state.get("output_message")
            if out_message is None:
                out_message = Message(
                    id=_gen_msg_id(),
                    type=MessageType.PLUGIN_CALL_OUTPUT,
                    role=Role.TOOL,
                    content=[],
                    status=RunStatus.InProgress,
                )
                out_message.name = "assistant"
                out_message.object = "message"

            out_message.add_content(new_content=final_content)
            yield self._tag_seq(final_content.completed())
            self._response.output.append(out_message)
            yield self._tag_seq(out_message.completed())

        # === DATA BLOCK ===
        elif evt_type == EventType.DATA_BLOCK_START.value:
            block_id = event.block_id
            media_type = getattr(event, "media_type", "")

            if not self._message_started:
                yield self._tag_seq(self._completed_message)
                self._message_started = True

            self._data_blocks[block_id] = {
                "media_type": media_type,
                "data_acc": "",
            }

        elif evt_type == EventType.DATA_BLOCK_DELTA.value:
            block_id = event.block_id
            state = self._data_blocks.get(block_id)
            if state is None:
                return
            state["data_acc"] += event.data or ""
            # No intermediate yield: partial base64 cannot be decoded or
            # rendered by the frontend.  Content is emitted once on
            # DATA_BLOCK_END with the complete payload.

        elif evt_type == EventType.DATA_BLOCK_END.value:
            block_id = event.block_id
            state = self._data_blocks.get(block_id)
            if state is None:
                return

            media_type = state["media_type"]
            b64_data = state["data_acc"]
            major = (media_type.split("/", 1)[0]) if media_type else ""
            index = len(self._completed_message.content)

            if major == "audio":
                fmt = media_type.split("/", 1)[1] if "/" in media_type else ""
                content_block = AudioContent(
                    type=ContentType.AUDIO,
                    data=b64_data,
                    format=fmt,
                    delta=False,
                    index=index,
                )
            elif major == "video":
                video_uri = f"data:{media_type};base64,{b64_data}"
                content_block = VideoContent(
                    type=ContentType.VIDEO,
                    video_url=video_uri,
                    delta=False,
                    index=index,
                )
            else:
                data_uri = f"data:{media_type};base64,{b64_data}"
                content_block = ImageContent(
                    type=ContentType.IMAGE,
                    image_url=data_uri,
                    delta=False,
                    index=index,
                )

            content_block.msg_id = self._message_id
            self._completed_message.content.append(content_block)
            yield self._tag_seq(content_block)

        # === MODEL_CALL_END ===
        elif evt_type == EventType.MODEL_CALL_END.value:
            input_tokens = getattr(event, "input_tokens", 0)
            output_tokens = getattr(event, "output_tokens", 0)
            usage = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
            self._response.usage = usage
            if self._message_started:
                self._completed_message.usage = usage

        # === EXCEED_MAX_ITERS ===
        elif evt_type == EventType.EXCEED_MAX_ITERS.value:
            agent_name = getattr(event, "name", "agent")
            err_msg_id = _gen_msg_id()
            err_message = Message(
                id=err_msg_id,
                type=MessageType.MESSAGE,
                role=Role.ASSISTANT,
                content=[],
                status=RunStatus.InProgress,
            )
            err_message.name = "assistant"
            err_message.object = "message"
            yield self._tag_seq(err_message)

            err_text = TextContent(
                type=ContentType.TEXT,
                text=(
                    f"[Warning] Agent '{agent_name}' has reached "
                    f"the maximum number of iterations."
                ),
                delta=False,
                index=0,
            )
            err_text.msg_id = err_msg_id
            yield self._tag_seq(err_text)

            err_message.content.append(err_text)
            err_message.status = RunStatus.Completed
            self._response.output.append(err_message)
            yield self._tag_seq(err_message)

        # === HINT_BLOCK (P2-2: warn and drop) ===
        elif evt_type == EventType.HINT_BLOCK.value:
            source = getattr(event, "source", None) or ""
            logger.warning(
                "HintBlockEvent received but not rendered: "
                "block_id=%s source=%s",
                getattr(event, "block_id", "?"),
                source,
            )

    # ------------------------------------------------------------------
    # Tool result content builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tool_result_content(
        call_id: str,
        state: Dict[str, Any],
        ContentType: Any,
        FunctionCallOutput: Any,
        tool_state: Any = None,
    ) -> Any:
        from ..schemas import DataContent

        blocks_dict: dict = state.get("output_data_blocks", {})
        text_acc: str = state.get("output_text_acc", "")

        if blocks_dict:
            output_blocks: list[dict[str, Any]] = list(
                blocks_dict.values(),
            )
            if text_acc:
                output_blocks.append({"type": "text", "text": text_acc})
            tool_output: Any = json.dumps(
                output_blocks,
                ensure_ascii=False,
            )
        else:
            tool_output = text_acc

        data_dict = FunctionCallOutput(
            call_id=call_id,
            name=state["name"],
            output=tool_output,
        ).model_dump()
        if tool_state is not None:
            data_dict["state"] = tool_state

        return DataContent(
            type=ContentType.DATA,
            data=data_dict,
            delta=False,
            index=0,
        )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def heartbeat(self) -> AsyncGenerator[Any, None]:
        yield self._tag_seq(self._response)

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
            yield self._tag_seq(self._completed_message)
            self._message_started = True

        tc = TextContent(
            type=ContentType.TEXT,
            text=cmd_text,
            delta=False,
            index=0,
        )
        tc.msg_id = self._message_id
        yield self._tag_seq(tc)

        self._completed_message.content.append(tc)
        self._completed_message.status = RunStatus.Completed
        self._completed_message.metadata = (
            getattr(cmd_msg, "metadata", None) or {}
        )
        self._response.output.append(self._completed_message)
        yield self._tag_seq(self._completed_message)

        self._response.status = RunStatus.Completed
        self._response.completed_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        yield self._tag_seq(self._response)
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
            yield self._tag_seq(self._completed_message)

        if self._error_text:
            self._response.status = RunStatus.Failed
            self._response.error = self._error_text
        else:
            self._response.status = RunStatus.Completed
        self._response.completed_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        yield self._tag_seq(self._response)
        self._finalized = True

    @property
    def response(self) -> Any:
        return self._response

    @property
    def agent_ref(self) -> Any:
        """Access point for the agent reference used in session save."""
        return None


__all__ = ["Envelope"]

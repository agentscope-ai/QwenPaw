# -*- coding: utf-8 -*-
# pylint: disable=too-many-nested-blocks
"""Runner base class — drives an agentscope 2.0 Agent and translates
events into the frontend's SSE envelope protocol."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict

from .heartbeat import (
    _iter_with_heartbeat,
    _HEARTBEAT_TICK,
    HEARTBEAT_INTERVAL_SECONDS,
)
from .agent_factory import build_agent
from .message_convert import (
    _get_last_user_text,
    _media_type_to_block_type,
    _request_input_to_msgs,
)

logger = logging.getLogger(__name__)


class Runner:
    """Base class providing lifecycle hooks and ``stream_query``.

    ``stream_query`` drives a 2.0 ``Agent`` via ``reply_stream`` and
    translates the event stream into the frontend's envelope protocol.
    ``AgentRunner`` inherits from this class.
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.session: Any = None

    async def start(self) -> None:
        """Default start: delegate to ``init_handler`` when defined."""
        init_handler = getattr(self, "init_handler", None)
        if init_handler is not None:
            await init_handler()

    async def stop(self) -> None:
        """Default stop: delegate to ``shutdown_handler`` when defined."""
        shutdown_handler = getattr(self, "shutdown_handler", None)
        if shutdown_handler is not None:
            await shutdown_handler()

    # pylint: disable=too-many-branches,too-many-statements
    async def stream_query(
        self,
        request: Any,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """Drive a stock 2.0 agent via ``reply_stream`` and translate the
        ``AgentEvent`` stream into the frontend's envelope protocol.

        Envelope sequence (matches ``Builder.tsx``)::

            1. response.created     (object=response, status=created)
            2. response.in_progress (object=response, status=in_progress)
            3. message.in_progress  (object=message, id=<msg-id>,
                                     status=in_progress, role=assistant,
                                     content=[])  — one per text block
            4. content (delta=true) (object=content, msg_id=<msg-id>,
                                     type=text, text=<piece>, index=<i>)
               …repeated per ``TextBlockDeltaEvent``…
            5. content (delta=false)(object=content, msg_id=<msg-id>,
                                     type=text, text=<full>, index=<i>)
               on ``TextBlockEndEvent`` to finalize.
            6. message.completed   (object=message, id=<msg-id>,
                                     status=completed, content=[full
                                     TextContent blocks])
            7. response.completed  (object=response, status=completed,
                                     output=[the message])

        Thinking blocks are emitted as a separate ``Message`` envelope with
        ``type=reasoning`` (one message per ``THINKING_BLOCK_START``), so the
        frontend's ``Reasoning`` card picks them up and renders them via
        ``<Thinking />``.  The flow mirrors the text-block path:

            a. message.in_progress  (object=message, id=<r-msg-id>,
                                     type=reasoning, status=in_progress,
                                     content=[])
            b. content (delta=true) (object=content, msg_id=<r-msg-id>,
                                     type=text, index=0, text=<piece>)
               …repeated per ``ThinkingBlockDeltaEvent``…
            c. content (delta=false)(object=content, msg_id=<r-msg-id>,
                                     type=text, index=0, text=<full>)
            d. message.completed   (object=message, id=<r-msg-id>,
                                     type=reasoning, status=completed,
                                     content=[full TextContent])

        Tool invocations are emitted as **two** ``Message`` envelopes per
        call (one ``plugin_call`` + one ``plugin_call_output``) which
        share the same ``call_id``; the frontend's ``mergeToolMessages``
        groups them by ``content[0].data.call_id`` and renders one
        ``<ToolCall>`` accordion whose ``loading`` state is driven by
        the merged message's ``status``:

            i. plugin_call message  (object=message, id=<in-msg-id>,
                                     type=plugin_call, status=completed,
                                     content=[DataContent(data={name,
                                     call_id, arguments})])
               emitted after ``TOOL_CALL_END`` once the JSON args have
               been fully accumulated from ``TOOL_CALL_DELTA`` events.

           ii. plugin_call_output message  (object=message,
                                            id=<out-msg-id>,
                                            type=plugin_call_output,
                                            status=in_progress,
                                            content=[])
               emitted at ``TOOL_RESULT_START`` — its ``in_progress``
               status drives the frontend spinner until the merge
               sibling lands.

          iii. plugin_call_output message  (..., status=completed,
                                            content=[DataContent(data={
                                            name, call_id, output,
                                            state})])
               emitted at ``TOOL_RESULT_END`` with the accumulated
               textual tool output and the final ``ToolResultState``.

        ``TOOL_RESULT_DATA_DELTA`` (binary/structured tool output) is
        accumulated into ``output_data_blocks`` and merged into the tool
        result envelope at ``TOOL_RESULT_END``.

        ``Reply`` and ``ModelCall`` events are silently ignored — they
        carry redundant information already captured by the text/tool
        event stream.
        """
        from agentscope.event import EventType
        from ..schemas import (
            AgentRequest,
            AgentResponse,
            ContentType,
            DataContent,
            Message,
            MessageType,
            Role,
            RunStatus,
            TextContent,
        )

        if isinstance(request, dict):
            request = AgentRequest(**request)

        if not getattr(request, "session_id", None):
            request.session_id = uuid.uuid4().hex
        if not getattr(request, "user_id", None):
            request.user_id = request.session_id

        session_id = request.session_id

        workspace_dir = getattr(self, "workspace_dir", None)

        # The middleware (RequestSetupMiddleware) handles per-request
        # ContextVars (workspace_dir, agent_id, session_id, shell config,
        # etc.) inside on_reply — it fires for both reply() and
        # reply_stream().  We only set workspace_dir/agent_id here for
        # consumers that run *before* the middleware chain (e.g. agent
        # factory resolving config paths).
        from ..config.context import set_current_workspace_dir
        from ..app.agent_context import (
            set_current_agent_id,
            set_current_session_id,
            set_current_root_session_id,
        )

        if workspace_dir is not None:
            set_current_workspace_dir(workspace_dir)
        set_current_agent_id(getattr(self, "agent_id", None) or "default")
        set_current_session_id(session_id or "")

        # Build the per-request context that tools (GuardedFunctionTool)
        # will use for approval routing.
        agent_id_for_ctx = getattr(self, "agent_id", None) or ""

        # Propagate root_session_id from parent agent (inter-agent calls).
        # If the request carries one, honour it; otherwise this session
        # is the root.
        payload_root_session = getattr(request, "root_session_id", "") or ""
        root_session_id = (
            payload_root_session
            if payload_root_session
            else (session_id or "")
        )
        set_current_root_session_id(root_session_id)

        request_context: dict[str, str] = {
            "session_id": session_id or "",
            "user_id": request.user_id or "",
            "channel": getattr(request, "channel", None) or "",
            "agent_id": agent_id_for_ctx,
            "root_session_id": root_session_id,
            "root_agent_id": agent_id_for_ctx,
        }

        # Propagate sender display name from channel_meta (IM nickname).
        _channel_meta = getattr(request, "channel_meta", None)
        if not isinstance(_channel_meta, dict):
            _channel_meta = {}
        _user_name = _channel_meta.get("user_name")
        if _user_name:
            request_context["user_name"] = _user_name

        # Merge extra context from request payload (inter-agent calls).
        _payload_ctx = getattr(request, "request_context", None)
        if isinstance(_payload_ctx, dict):
            request_context.update(_payload_ctx)

        logger.info(
            "stream_query: enter session=%s workspace=%s input_len=%s",
            session_id,
            workspace_dir,
            len(getattr(request, "input", []) or []),
        )

        response = AgentResponse(output=[], status=RunStatus.Created)
        response.object = "response"
        response.session_id = session_id
        yield response

        response.status = RunStatus.InProgress
        yield response

        raw_input = getattr(request, "input", []) or []

        # The Message envelope we accumulate into and emit twice: once with
        # empty content (in_progress) so the frontend can register the msg.id
        # and route subsequent ``content`` events to it, then again with the
        # finalized content list at completion.
        message_id = uuid.uuid4().hex
        completed_message = Message(
            id=message_id,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[],
            status=RunStatus.InProgress,
        )
        completed_message.name = "assistant"
        completed_message.object = "message"
        message_started = False

        # block_id -> (index, accumulated_text)
        text_blocks: Dict[str, Dict[str, Any]] = {}
        # block_id -> {msg_id, envelope, text}
        reasoning_blocks: Dict[str, Dict[str, Any]] = {}
        # tool_call_id -> {input_msg_id, output_msg_id, name,
        #                  args_json_acc, output_text_acc}
        tool_calls: Dict[str, Dict[str, Any]] = {}

        error_text: str | None = None
        agent = None
        try:
            msgs = _request_input_to_msgs(raw_input)

            # Get MCP clients from workspace manager
            mcp_clients = None
            mcp_mgr = getattr(self, "_mcp_manager", None)
            if mcp_mgr is not None:
                try:
                    mcp_clients = await mcp_mgr.get_clients()
                except Exception:
                    logger.debug(
                        "stream_query: failed to get MCP clients",
                        exc_info=True,
                    )

            agent = build_agent(
                session_id,
                agent_id=getattr(self, "agent_id", None),
                workspace_dir=workspace_dir,
                mcp_clients=mcp_clients or None,
                request_context=request_context,
                memory_manager=getattr(self, "memory_manager", None),
                context_manager=getattr(self, "context_manager", None),
            )

            # Load persisted session state (conversation history).
            session = getattr(self, "session", None)
            if session is not None:
                try:
                    user_id = getattr(request, "user_id", "") or session_id
                    channel = getattr(request, "channel", "") or ""
                    await session.load_session_state(
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        agent=agent,
                    )
                except KeyError as e:
                    logger.debug(
                        "stream_query: session load skipped "
                        "(schema mismatch): %s",
                        e,
                    )
                except Exception:
                    logger.debug(
                        "stream_query: session load failed",
                        exc_info=True,
                    )

            # Slash-command interception: conversation, daemon, control,
            # and skill commands are all dispatched here before driving
            # the model.
            _last_text = _get_last_user_text(msgs)
            if _last_text and _last_text.startswith("/"):
                from ..app.runner.command_dispatch import dispatch_command

                cmd_msg = await dispatch_command(
                    _last_text,
                    agent=agent,
                    runner=self,
                    request=request,
                    msgs=msgs,
                )
                if cmd_msg is not None:
                    cmd_text = cmd_msg.get_text_content() or ""
                    yield completed_message
                    message_started = True
                    tc = TextContent(
                        type=ContentType.TEXT,
                        text=cmd_text,
                        delta=False,
                        index=0,
                    )
                    tc.msg_id = message_id
                    tc.object = "content"
                    yield tc
                    completed_message.content.append(tc)
                    completed_message.status = RunStatus.Completed
                    completed_message.metadata = (
                        getattr(cmd_msg, "metadata", None) or {}
                    )
                    response.output.append(completed_message)
                    yield completed_message
                    response.status = RunStatus.Completed
                    yield response
                    # Persist state (commands like /clear modify agent.state)
                    session = getattr(self, "session", None)
                    if session is not None and agent is not None:
                        try:
                            await session.save_session_state(
                                session_id=session_id,
                                user_id=(
                                    getattr(request, "user_id", "")
                                    or session_id
                                ),
                                channel=(
                                    getattr(request, "channel", "") or ""
                                ),
                                agent=agent,
                            )
                        except Exception:
                            logger.debug(
                                "stream_query: command path state persist "
                                "failed",
                                exc_info=True,
                            )
                    return

            # Refresh system prompt so edits to AGENTS.md / SOUL.md /
            # PROFILE.md take effect immediately without restarting the
            # session (mirrors the per-turn refresh that 1.x query_handler
            # performed).
            rebuild = getattr(agent, "rebuild_sys_prompt", None)
            if rebuild is not None:
                rebuild()

            # Wrap reply_stream so long idle periods (notably tool-guard
            # ASK waits up to TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS=300s) emit
            # SSE-keepalive heartbeats instead of letting the connection
            # silently drop at the proxy / browser idle-timeout boundary.
            agent_iter = agent.reply_stream(inputs=msgs).__aiter__()
            async for event in _iter_with_heartbeat(
                agent_iter,
                HEARTBEAT_INTERVAL_SECONDS,
            ):
                if event is _HEARTBEAT_TICK:
                    # Re-yield the in-progress response envelope.  Status
                    # hasn't changed; the frontend's response reducer is
                    # idempotent on duplicate in_progress events (the
                    # startup path already emits Created→InProgress twice).
                    # The bytes hitting the wire keep proxies happy.
                    yield response
                    continue

                evt_type = getattr(event, "type", None)
                if hasattr(evt_type, "value"):
                    evt_type = evt_type.value

                if evt_type == EventType.TEXT_BLOCK_START.value:
                    if not message_started:
                        yield completed_message
                        message_started = True
                    block_id = event.block_id
                    index = len(text_blocks)
                    text_blocks[block_id] = {"index": index, "text": ""}

                elif evt_type == EventType.TEXT_BLOCK_DELTA.value:
                    if not message_started:
                        yield completed_message
                        message_started = True
                    block_id = event.block_id
                    delta = event.delta or ""
                    # Tolerate missing TEXT_BLOCK_START; register lazily.
                    state = text_blocks.setdefault(
                        block_id,
                        {"index": len(text_blocks), "text": ""},
                    )
                    state["text"] += delta
                    chunk = TextContent(
                        type=ContentType.TEXT,
                        text=delta,
                        delta=True,
                        index=state["index"],
                    )
                    chunk.msg_id = message_id
                    chunk.object = "content"
                    yield chunk

                elif evt_type == EventType.TEXT_BLOCK_END.value:
                    block_id = event.block_id
                    state = text_blocks.get(block_id)
                    if state is None:
                        continue
                    final_chunk = TextContent(
                        type=ContentType.TEXT,
                        text=state["text"],
                        delta=False,
                        index=state["index"],
                    )
                    final_chunk.msg_id = message_id
                    final_chunk.object = "content"
                    yield final_chunk
                    # Mirror into the completed-message envelope so
                    # downstream consumers that read it directly (e.g. console
                    # terminal pretty-print) see the full text.
                    completed_message.content.append(
                        TextContent(
                            type=ContentType.TEXT,
                            text=state["text"],
                            delta=False,
                            index=state["index"],
                        ),
                    )

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
                    reasoning_blocks[block_id] = {
                        "msg_id": r_msg_id,
                        "envelope": r_envelope,
                        "text": "",
                    }
                    yield r_envelope

                elif evt_type == EventType.THINKING_BLOCK_DELTA.value:
                    block_id = event.block_id
                    delta = getattr(event, "delta", "") or ""
                    state = reasoning_blocks.get(block_id)
                    if state is None:
                        # Lazy-register on a missing THINKING_BLOCK_START.
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
                        reasoning_blocks[block_id] = state
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
                    state = reasoning_blocks.get(block_id)
                    if state is None:
                        continue
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
                    response.output.append(state["envelope"])
                    yield state["envelope"]

                elif evt_type == EventType.TOOL_CALL_START.value:
                    # Allocate an envelope id but don't emit yet — the
                    # frontend's ToolCall card wants the full args at
                    # render time, which we only have at TOOL_CALL_END.
                    tool_calls[event.tool_call_id] = {
                        "input_msg_id": uuid.uuid4().hex,
                        "name": event.tool_call_name,
                        "args_json_acc": "",
                        "output_text_acc": "",
                    }

                elif evt_type == EventType.TOOL_CALL_DELTA.value:
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        # Lazy-register on a missing TOOL_CALL_START.
                        state = {
                            "input_msg_id": uuid.uuid4().hex,
                            "name": "",
                            "args_json_acc": "",
                            "output_text_acc": "",
                        }
                        tool_calls[event.tool_call_id] = state
                    state["args_json_acc"] += event.delta or ""

                elif evt_type == EventType.TOOL_CALL_END.value:
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        continue
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
                    response.output.append(in_envelope)
                    yield in_envelope

                elif evt_type == EventType.TOOL_RESULT_START.value:
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        # Lazy-register so we still emit something coherent.
                        state = {
                            "input_msg_id": uuid.uuid4().hex,
                            "name": event.tool_call_name,
                            "args_json_acc": "",
                            "output_text_acc": "",
                        }
                        tool_calls[event.tool_call_id] = state
                    state["output_msg_id"] = uuid.uuid4().hex
                    # The in_progress envelope needs the call_id in its
                    # ``content[0].data`` so ``mergeToolMessages`` in
                    # Builder.tsx can pair it with the matching plugin_call
                    # while we're still streaming the tool output — that's
                    # the merge that drives ``<ToolCall loading>``.  An
                    # empty content[] would float this message separately
                    # and the spinner wouldn't fire on the unified card.
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
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        continue
                    state["output_text_acc"] += event.delta or ""

                elif evt_type == EventType.TOOL_RESULT_DATA_DELTA.value:
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        continue
                    data_blocks = state.setdefault(
                        "output_data_blocks",
                        [],
                    )
                    media_type = getattr(event, "media_type", None)
                    block_type = _media_type_to_block_type(
                        media_type,
                    )
                    block: dict[str, Any] = {
                        "type": block_type,
                        "source": {},
                    }
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
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        continue
                    tool_state = getattr(event, "state", None)
                    if hasattr(tool_state, "value"):
                        tool_state = tool_state.value
                    data_blocks = state.get("output_data_blocks")
                    if data_blocks:
                        output_blocks: list[dict[str, Any]] = list(
                            data_blocks,
                        )
                        text_acc = state["output_text_acc"]
                        if text_acc:
                            output_blocks.append(
                                {"type": "text", "text": text_acc},
                            )
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
                        # No TOOL_RESULT_START seen; build envelope now.
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
                    response.output.append(out_envelope)
                    yield out_envelope

                # Other events (Reply/ModelCall) — not needed by channels.

        except Exception as exc:
            logger.exception("stream_query: reply_stream raised")

            # Normalize provider-specific errors (rate limit, auth,
            # context-too-long) into user-readable exceptions.
            from ..exceptions import convert_model_exception

            model_name: str | None = None
            try:
                if agent is not None:
                    _m = getattr(agent, "model", None)
                    if _m is not None:
                        model_name = getattr(
                            _m,
                            "model_name",
                            None,
                        ) or getattr(_m, "name", None)
            except Exception:
                pass

            normalized = convert_model_exception(exc, model_name=model_name)
            error_text = (
                normalized.message or str(exc) or exc.__class__.__name__
            )

            # Write agent state + traceback to a temp file for debugging.
            try:
                from ..app.runner.query_error_dump import (
                    write_query_error_dump,
                )

                dump_path = write_query_error_dump(
                    request,
                    exc,
                    {"agent": agent},
                )
                if dump_path:
                    error_text += f" [dump: {dump_path}]"
                    logger.info(
                        "stream_query: error dump written to %s",
                        dump_path,
                    )
            except Exception:
                logger.debug(
                    "stream_query: write_query_error_dump failed",
                    exc_info=True,
                )

        except BaseException as exc:
            # CancelledError (Python 3.11+: not an Exception subclass).
            # Clean up pending approvals so they don't block future turns,
            # and give the agent a chance to tidy up internal state.
            logger.info(
                "stream_query: cancelled (session=%s): %s",
                session_id,
                type(exc).__name__,
            )
            try:
                from ..app.approvals import get_approval_service

                svc = get_approval_service()
                await svc.cancel_all_pending_by_root_session(
                    request_context.get("root_session_id", session_id),
                )
            except Exception:
                logger.debug(
                    "stream_query: approval cleanup failed",
                    exc_info=True,
                )
            interrupt_fn = getattr(agent, "interrupt", None) if agent else None
            if interrupt_fn is not None:
                try:
                    interrupt_fn()
                except Exception:
                    pass
            raise

        if message_started:
            completed_message.status = RunStatus.Completed
            response.output.append(completed_message)
            yield completed_message

        if error_text:
            response.status = RunStatus.Failed
            response.error = error_text
        else:
            response.status = RunStatus.Completed
        yield response

        # Persist agent state so the frontend's chat-history API and
        # session reload see the conversation even after a restart.
        try:
            session = getattr(self, "session", None)
            if session is not None and agent is not None:
                user_id = getattr(request, "user_id", "") or session_id
                channel = getattr(request, "channel", "") or ""
                await session.save_session_state(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    agent=agent,
                )
        except Exception:
            logger.debug(
                "stream_query: failed to persist session state",
                exc_info=True,
            )

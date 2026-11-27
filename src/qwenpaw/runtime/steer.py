# -*- coding: utf-8 -*-
"""Request-bound steering at native agent reasoning boundaries."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from agentscope.event import ReplyEndEvent
from agentscope.middleware import MiddlewareBase
from agentscope.types import ReplyFinishedReason

from .._session_signals import TRANSCRIPT_TURN_ID_CONTEXT_KEY
from ..utils.io_utils import run_async_to_completion
from ..schemas import Message
from .message_convert import _request_input_to_msgs

current_steer: ContextVar[Any] = ContextVar("current_steer", default=None)


@dataclass
class SteerOutput:
    """A standard envelope already prepared at the input boundary."""

    output: Any
    type: str = "qwenpaw.steer"


class SteerControl:
    """Own one turn's admission and next-step commit decisions."""

    def __init__(self, recorder):
        self.recorder = recorder
        self.turn_id = recorder.turn_id
        self.scope = ""
        self.lock = asyncio.Lock()
        self.agent = None
        self.envelope = None
        self.closed = False
        self.pending = []

    def owns_request(self, request):
        context = getattr(request, "request_context", None) or {}
        return context.get(TRANSCRIPT_TURN_ID_CONTEXT_KEY) == self.turn_id

    @property
    def unavailable(self):
        if self.closed or self.agent is None or self.envelope is None:
            return "no_active_turn"
        if not self.recorder.ready:
            return "transcript_unavailable"
        if self.agent.state.reply_context.structured_schema is not None:
            return "structured_output"
        if self.agent.state.has_awaiting_tool_calls(self.agent.name):
            return "blocking_interaction"
        if self.agent.state.cur_iter >= self.agent.react_config.max_iters:
            return "iteration_limit"
        return None

    async def accept(self, client_message_id, content):
        fields = {
            "text": "text",
            "image": "image_url",
            "audio": "data",
            "video": "video_url",
            "file": "file_url",
        }
        if not content or any(
            part.get("type") not in fields
            or not isinstance(part.get(fields[part["type"]]), str)
            or not part[fields[part["type"]]].strip()
            for part in content
        ):
            raise ValueError("unsupported_content")
        # Validate with the same envelope schema as ordinary user input.
        Message(role="user", content=content)
        async with self.lock:
            if self.unavailable:
                raise ValueError(self.unavailable)

            async def persist():
                receipt = await self.recorder.steer_io(
                    "accept_steer",
                    client_message_id=client_message_id,
                    content=content,
                )
                if receipt["status"] == "accepted" and not any(
                    r["client_message_id"] == client_message_id
                    for r in self.pending
                ):
                    self.pending.append(receipt)
                return receipt

            return await run_async_to_completion(persist())

    async def apply(self, agent):
        async with self.lock:
            if not self.pending or self.closed:
                return
            if self.unavailable:
                await self._close(self.unavailable)
                return
            batch = list(self.pending)
        # The consumer records this segment before allocating steer ordinals.
        # Never hold admission's lock while waiting for that consumer.
        async for obj in self.envelope.close_input_segment():
            yield SteerOutput(obj)
        async with self.lock:
            if self.closed:
                return
            if self.unavailable:
                await self._close(self.unavailable)
                return
            messages = [self.envelope.prepare_steer(r) for r in batch]
            converted = _request_input_to_msgs(messages)
            if len(converted) != len(messages) or any(
                len(msg.content) != len(source.content)
                for msg, source in zip(converted, messages)
            ):
                await self._close("unsupported_content")
                return
            for msg, source in zip(converted, messages):
                msg.id = source.id
            context = [*agent.state.context, *converted]

            async def commit():
                await self.recorder.apply_steers(
                    messages,
                    agent.state.cur_iter,
                )
                agent.state.context = context
                marker = agent.state.middle_context.get(
                    "qwenpaw_steer_boundary",
                )
                applied = (
                    marker["message_ids"]
                    if marker and marker["turn_id"] == self.turn_id
                    else []
                )
                agent.state.middle_context["qwenpaw_steer_boundary"] = {
                    "turn_id": self.turn_id,
                    "message_ids": [*applied, *(m.id for m in messages)],
                }
                applied_ids = {r["client_message_id"] for r in batch}
                self.pending[:] = [
                    r
                    for r in self.pending
                    if r["client_message_id"] not in applied_ids
                ]
                for message in messages:
                    self.envelope.append_steer(message)

            await run_async_to_completion(commit())
        for message in messages:
            yield SteerOutput(message)

    async def continue_reply(self, reason):
        async with self.lock:
            if (
                reason == ReplyFinishedReason.COMPLETED
                and self.pending
                and not self.unavailable
            ):
                return True
            await self._close(
                self.unavailable or str(reason),
            )
            return False

    async def _close(self, reason):
        self.closed = True
        if self.pending:
            await self.recorder.steer_io("fail_steers", reason=reason)
        self.pending.clear()

    async def close(self, reason="turn_finished"):
        async with self.lock:
            await self._close(reason)


class SteerMiddleware(MiddlewareBase):
    """Continue normal exits only when a pending input has budget."""

    def __init__(self, control):
        self.control = control

    async def on_reply(self, agent, input_kwargs, next_handler):
        self.control.agent = agent
        async for event in next_handler(**input_kwargs):
            if isinstance(event, ReplyEndEvent):
                if await self.control.continue_reply(event.finished_reason):
                    continue
            yield event

    async def on_reasoning(self, agent, input_kwargs, next_handler):
        async for event in self.control.apply(agent):
            yield event
        async for event in next_handler(**input_kwargs):
            yield event

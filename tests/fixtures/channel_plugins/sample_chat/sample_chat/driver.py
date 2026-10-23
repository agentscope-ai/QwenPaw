# -*- coding: utf-8 -*-
"""Executable generic Channel example with an offline SDK boundary."""

import asyncio
import os
import uuid

from qwenpaw.channel_protocol.errors import RPC_LIFECYCLE_ERROR, RpcError
from qwenpaw.channel_protocol.models import InboundEvent
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)

from .sdk import DeliveryError, PID


class Driver(SharedResponseDriver):
    def __init__(self):
        super().__init__("sample", "sample.responses", DeliveryError)
        self.effects = []
        self.policy_reads = 0
        self.finish_calls = []
        self.fault = ""

    def bind(self, context):
        super().bind(context)
        for method, handler in (
            ("fixture.emit", self.emit),
            ("fixture.inspect", self.inspect),
            ("fixture.fault", self.set_fault),
        ):
            context.peer.register_method(method, handler)

    async def start(self, config):
        self._config = dict(config)
        self._connected = True
        self._platform = self
        self._connection_generation += 1
        await self._restore_responses()
        await self._context.set_platform_state("connected")

    async def stop(self):
        self._stopping = True
        await self._checkpoint()
        self._connected = False
        await self._context.set_platform_state("disconnected")

    def _check_connection(self, generation):
        if self._stopping or generation != self._connection_generation:
            raise RuntimeError("STALE_CONNECTION_CALLBACK")

    def _require_connected(self):
        if not self._connected:
            raise ValueError("NOT_CONNECTED")
        return self

    async def inspect(self, _params, _request):
        return {
            "pid": os.getpid(),
            "sdk_pid": PID,
            "source": __file__,
            "effects": self.effects,
            "policy_reads": self.policy_reads,
            "finish_calls": self.finish_calls,
            "identity": self._context.identity.to_mapping(),
            "routes": [row.to_mapping() for row in self._routes.snapshots()],
        }

    async def set_fault(self, params, _request):
        self.fault = params["mode"]
        return {}

    async def _open(self, params, _request):
        self._identity(params)
        from qwenpaw.channel_protocol.targets import decode_reply_target

        decoded = decode_reply_target(params["to_handle"])
        room = (
            decoded["session_id"]
            if decoded
            else params["to_handle"].removeprefix("sample:old:")
        )
        if room not in self._config["rooms"]:
            raise RpcError(
                RPC_LIFECYCLE_ERROR,
                "unknown target",
                data={
                    "reason_code": "OUTBOUND_TARGET_UNKNOWN",
                    "retryable": False,
                },
            )
        handle = "sample:reply:" + uuid.uuid4().hex
        await self._persist_route(handle, {"room": room})
        return {"response_handle": handle}

    def response_policy(self, response_handle):
        self.policy_reads += 1
        if self.fault == "describe-error":
            raise RpcError(
                RPC_LIFECYCLE_ERROR,
                "describe unavailable",
                data={
                    "reason_code": "DESCRIBE_UNAVAILABLE",
                    "retryable": False,
                },
            )
        from qwenpaw.channel_protocol.response_policy import ResponsePolicy

        room = self._route_attrs(response_handle)["room"]
        return ResponsePolicy.from_mapping(
            self._config["route_policies"].get(
                room,
                {
                    "streaming": False,
                    "prepare": False,
                    "completion_reaction": False,
                },
            ),
        )

    async def emit(self, params, _request):
        raw = params["event"]
        handle = "sample:reply:" + uuid.uuid4().hex
        await self._persist_route(handle, {"room": raw.get("room", "room-A")})
        metadata = {
            "session_id": raw.get("session_id", "historic-room-A"),
            "user_id": raw.get("user_id", "group"),
            "debounce_key": raw.get(
                "debounce_key",
                "historic-room-A:" + raw.get("actor", "actor-A"),
            ),
            "bot_mentioned": raw.get("bot_mentioned", True),
            **raw.get("metadata", {}),
        }
        event = InboundEvent.from_mapping(
            {
                **self._context.identity.to_mapping(),
                **raw.get("identity", {}),
                "event_id": raw["id"],
                "event_kind": "message",
                "conversation": {
                    "id": raw.get("room", "room-A"),
                    "type": raw.get("type", "group"),
                    "thread_id": raw.get("thread_id"),
                },
                "sender_id": raw.get("sender", "Alice"),
                "sender_name": raw.get("sender", "Alice"),
                "acl_sender_id": raw.get("actor", "actor-A"),
                "content_parts": raw.get(
                    "content_parts",
                    [{"type": "text", "text": raw.get("text", "hello")}],
                ),
                "metadata": metadata,
                "response_handle": handle,
            },
        )
        if raw.get("shared_admission"):
            admitted = await self._admit_event(event, True)
            return (
                admitted[0].to_mapping()
                if admitted
                else {"accepted_event_ids": []}
            )
        return await self._context.peer.call(
            "event.batch",
            {"batch_id": raw["id"], "events": [event.to_mapping()]},
        )

    async def _perform_prepare(self, params):
        return await self.effect("prepare", params)

    async def _perform_send(self, params):
        return await self.effect(params.operation.value, params)

    async def _perform_reaction(self, params):
        return await self.effect("reaction", params)

    async def effect(self, operation, params):
        self.effects.append(
            {
                "operation": operation,
                "room": self._route_attrs(params.to_handle)["room"],
                "delivery_id": params.delivery_id,
                "pid": os.getpid(),
                "content_parts": list(getattr(params, "content_parts", ())),
            },
        )
        if self.fault == "prepare-refused" and operation == "prepare":
            raise DeliveryError(
                "PLATFORM_PREPARE_REFUSED",
                side_effect_possible=False,
            )
        if self.fault == "unknown":
            raise DeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        if self.fault == "delay":
            await asyncio.sleep(30)
        return ResponseResourceRef.create(
            "sample.delivery",
            params.delivery_id,
            {"operation": operation},
        )

    async def _finish(self, params, request):
        self.finish_calls.append(params.to_mapping())
        return await super()._finish(params, request)

    async def _before_cleanup_complete(self, snapshot):
        self.effects.append(
            {
                "operation": "finish",
                "outcome": snapshot.outcome.value,
                "response_handle": snapshot.response_handle,
                "pid": os.getpid(),
            },
        )
        return snapshot

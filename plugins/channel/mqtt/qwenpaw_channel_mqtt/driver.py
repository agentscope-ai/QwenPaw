# -*- coding: utf-8 -*-
"""MQTT generic Driver; Agent execution and access control stay in the host."""

from __future__ import annotations

import uuid

from qwenpaw.channel_protocol.models import InboundEvent
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.channel_protocol.targets import decode_reply_target
from .platform import MQTTDeliveryError, MQTTPlatform


class MQTTDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__("mqtt", "mqtt.shared.responses", MQTTDeliveryError)

    async def start(self, config):
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        for snapshot in self._routes.pending_cleanups():
            async with self._lock(snapshot.response_handle):
                await self._cleanup(snapshot)
        self._platform = MQTTPlatform(
            self._config,
            self._message,
            self._state_changed,
        )
        await self._state_changed("connecting")
        try:
            await self._platform.start()
        except BaseException:
            await self._state_changed("failed")
            raise

    async def _state_changed(self, state):
        self._connected = state == "connected"
        self._connection_generation += 1
        await self._context.set_platform_state(state)

    def _require_connected(self):
        if not self._connected or self._stopping or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        return ResponsePolicy(send_format=SendFormatPolicy(False, False))

    def _target(self, handle, meta):
        if meta.get("client_id"):
            return str(meta["client_id"])
        target = decode_reply_target(str(handle))
        if target is not None:
            session = target["session_id"]
            return (
                session.split(":", 1)[-1]
                if session.startswith("mqtt:")
                else target["user_id"]
            )
        session = str(meta.get("session_id") or handle)
        return (
            session.split(":", 1)[-1]
            if session.startswith("mqtt:")
            else str(handle)
        )

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        meta = dict(params.get("meta") or {})
        target = self._target(params["to_handle"], meta)
        if not target:
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        handle = "mqtt:reply:" + uuid.uuid4().hex
        await self._persist_route(handle, {"client_id": target})
        return {"response_handle": handle}

    async def _message(self, value):
        sender = value["sender"]
        handle = "mqtt:reply:" + value["event_id"]
        await self._persist_route(handle, {"client_id": sender})
        session = "mqtt:" + sender
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=value["event_id"],
            event_kind="message",
            conversation={"id": sender, "type": "dm", "thread_id": None},
            sender_id=sender,
            acl_sender_id=sender,
            sender_name="",
            content_parts=({"type": "text", "text": value["text"]},),
            metadata={
                "session_id": session,
                "user_id": sender,
                "debounce_key": session,
                "topic": value["topic"],
                "client_id": sender,
                "raw_payload": value["payload"],
            },
            response_handle=handle,
        )
        await self._admit_event(event, True)

    async def _perform_send(self, params):
        platform = self._require_connected()
        if params.operation.value != "message.create":
            raise MQTTDeliveryError("OPERATION_UNSUPPORTED")
        resource = await platform.publish_parts(
            self._route_attrs(params.to_handle)["client_id"],
            params.content_parts,
        )
        return ResponseResourceRef.create(
            "mqtt.delivery",
            params.delivery_id,
            resource,
        )

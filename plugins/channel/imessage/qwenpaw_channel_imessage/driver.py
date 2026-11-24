# -*- coding: utf-8 -*-
"""iMessage routes and receipts over the shared response protocol."""

from __future__ import annotations

import hashlib
import uuid

from qwenpaw.channel_protocol.models import InboundEvent
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.channel_protocol.targets import decode_reply_target

from .platform import IMessageDeliveryError, IMessagePlatform


class IMessageDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "imessage",
            "imessage.shared.responses",
            IMessageDeliveryError,
        )

    async def start(self, config):
        if self._platform is not None:
            raise RuntimeError("IMESSAGE_RESOURCES_ALREADY_OWNED")
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        for snapshot in self._routes.pending_cleanups():
            async with self._lock(snapshot.response_handle):
                await self._cleanup(snapshot)
        if not self._config.get("enabled", False):
            await self._state_changed("disconnected")
            return
        self._platform = IMessagePlatform(
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
        connected = state == "connected"
        if connected != self._connected:
            self._connection_generation += 1
        self._connected = connected
        await self._context.set_platform_state(state)

    def _require_connected(self):
        if not self._connected or self._stopping or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        # iMessage prefixes parts without the generic two-space separator,
        # and strips only after prefix+body are combined in the platform.
        return ResponsePolicy(
            send_format=SendFormatPolicy(False, False, False, False, False),
        )

    @staticmethod
    def _target(handle, meta):
        decoded = decode_reply_target(str(handle))
        sender = decoded["user_id"] if decoded else str(handle)
        session = decoded["session_id"] if decoded else str(handle)
        if session.startswith("imessage:"):
            sender = session.removeprefix("imessage:")
        if not sender.strip():
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        return {
            "sender": sender,
            "bot_prefix": str(meta.get("bot_prefix") or ""),
            "chat_rowid": str(meta.get("chat_rowid") or ""),
            "rowid": str(meta.get("rowid") or ""),
        }

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        handle = "imessage:reply:" + uuid.uuid4().hex
        await self._persist_route(
            handle,
            self._target(params["to_handle"], params.get("meta") or {}),
        )
        return {"response_handle": handle}

    async def _message(self, value):
        self._require_connected()
        event_id, sender = value["event_id"], value["sender"]
        handle = (
            "imessage:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        session = "imessage:" + sender
        meta = {
            "chat_rowid": value["chat_rowid"],
            "rowid": value["rowid"],
        }
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if created or snapshot.kind.value != "terminal":
            await self._persist_route(
                handle,
                self._target(
                    session,
                    {**meta, "bot_prefix": self._config.get("bot_prefix", "")},
                ),
            )
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind="message",
            conversation={"id": sender, "type": "dm", "thread_id": None},
            sender_id=sender,
            acl_sender_id=sender,
            sender_name=sender,
            content_parts=({"type": "text", "text": value["text"]},),
            metadata={
                **meta,
                "session_id": session,
                "user_id": sender,
                "debounce_key": session,
            },
            response_handle=handle,
        )
        return await self._admit_event(event, created) is not None

    async def _perform_send(self, params):
        platform = self._require_connected()
        if params.operation.value != "message.create":
            raise IMessageDeliveryError("OPERATION_UNSUPPORTED")
        route = self._route_attrs(params.to_handle)
        result = await platform.send_parts(
            route["sender"],
            params.content_parts,
            params.content_source,
            route.get("bot_prefix", ""),
        )
        return ResponseResourceRef.create(
            "imessage.delivery",
            params.delivery_id,
            result,
        )

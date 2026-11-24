# -*- coding: utf-8 -*-
"""Yuanbao routes and native effects over the common shared worker contract."""

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

from .errors import YuanbaoDeliveryError
from .platform import YuanbaoPlatform


class YuanbaoDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "yuanbao",
            "yuanbao.shared.responses",
            YuanbaoDeliveryError,
        )

    async def start(self, config):
        if self._platform is not None:
            raise RuntimeError("YUANBAO_RESOURCES_ALREADY_OWNED")
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        if not self._config.get("enabled", False):
            await self._state_changed("disconnected")
            return
        self._platform = YuanbaoPlatform(
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
        if connected and self._platform is not None:
            self._platform._spawn(self._resume_cleanups())

    async def _resume_cleanups(self):
        for snapshot in self._routes.pending_cleanups():
            try:
                async with self._lock(snapshot.response_handle):
                    await self._cleanup(snapshot)
            except Exception:
                await self._diagnostic("YUANBAO_RESPONSE_CLEANUP_PENDING")

    def _require_connected(self):
        if self._stopping or not self._connected or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        return ResponsePolicy(
            prepare=True,
            send_format=SendFormatPolicy(False, True),
        )

    async def _open(self, params, request):
        self._identity(params)
        platform = self._require_connected()
        meta = dict(params.get("meta") or {})
        decoded = decode_reply_target(str(params["to_handle"]))
        session = (
            (decoded["session_id"] or decoded["user_id"])
            if decoded
            else str(params["to_handle"])
        )
        route = platform.resolve_target(session, meta)
        handle = "yuanbao:reply:" + uuid.uuid4().hex
        await self._persist_route(handle, route)
        return {"response_handle": handle}

    async def _message(self, value):
        self._require_connected()
        event_id = value["event_id"]
        handle = (
            "yuanbao:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if created or snapshot.kind.value != "terminal":
            await self._persist_route(handle, value["route"])
        session = value["session_id"]
        route = value["route"]
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind="message",
            conversation={
                "id": (
                    route["group_code"]
                    if route["chat_type"] == "group"
                    else value["raw_sender_id"]
                ),
                "type": "group" if route["chat_type"] == "group" else "dm",
                "thread_id": None,
            },
            sender_id=value["sender_id"],
            acl_sender_id=value["raw_sender_id"],
            sender_name=value["sender_name"],
            content_parts=tuple(value["content_parts"]),
            metadata={
                **value["meta"],
                "user_id": value["sender_id"],
                "session_id": session,
                "debounce_key": session,
            },
            response_handle=handle,
        )
        return await self._admit_event(event, created) is not None

    async def _perform_send(self, params):
        if params.operation.value != "message.create":
            raise YuanbaoDeliveryError("OPERATION_UNSUPPORTED")
        platform = self._require_connected()
        receipt = await platform.send_parts(
            self._route_attrs(params.to_handle),
            params.content_parts,
            params.content_source,
            params.delivery_id,
        )
        return ResponseResourceRef.create(
            "yuanbao.delivery",
            params.delivery_id,
            receipt,
        )

    async def _perform_prepare(self, params):
        platform = self._require_connected()
        attributes = {
            "typing": "true",
            "owner": params.to_handle,
            "scope": "websocket.write",
            "transport_written": "unknown",
        }
        # Journal the potential transient effect before writing. Cancellation
        # or a missing prepare receipt must still retain a FINISH obligation.
        resource = ResponseResourceRef.create(
            "yuanbao.delivery",
            params.delivery_id,
            attributes,
        )
        self._routes.record_delivery(params.to_handle, [resource])
        await self._checkpoint()
        receipt = await platform.start_typing(
            params.to_handle,
            self._route_attrs(params.to_handle),
        )
        attributes.update(
            native_message_id=receipt.request_id,
            transport_written="true",
        )
        return ResponseResourceRef.create(
            "yuanbao.delivery",
            params.delivery_id,
            attributes,
        )

    def _needs_stream_cleanup(self, ref):
        needed = dict(ref.attributes).get("typing") == "true"
        if needed:
            self._require_connected()
        return needed

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        platform = self._require_connected()
        owner = resource["owner"]
        # Cleanup snapshots are terminal; active_route_refs intentionally
        # rejects them. Read this response's immutable retained native route.
        snapshot = self._routes.snapshot(owner)
        route = dict(snapshot.route_refs[0].attributes)
        await platform.stop_typing(owner, route)

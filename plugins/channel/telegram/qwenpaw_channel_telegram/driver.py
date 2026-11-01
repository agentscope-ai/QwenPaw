# -*- coding: utf-8 -*-
"""Telegram response ownership over the common worker protocol."""

from __future__ import annotations

import hashlib
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
from .errors import TelegramDeliveryError


class TelegramDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "telegram",
            "telegram.shared.responses",
            TelegramDeliveryError,
        )

    async def start(self, config):
        from .platform import TelegramPlatform

        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        self._platform = TelegramPlatform(
            self._config,
            self._message,
            self._state_changed,
            self._callback,
        )
        await self._state_changed("connecting")
        try:
            await self._platform.start()
        except BaseException:
            await self._state_changed("failed")
            raise

    async def _state_changed(self, state):
        connected = state == "connected"
        if self._connected != connected:
            self._connection_generation += 1
        self._connected = connected
        await self._context.set_platform_state(state)
        if connected:
            for snapshot in self._routes.pending_cleanups():
                async with self._lock(snapshot.response_handle):
                    try:
                        await self._cleanup(snapshot)
                    except Exception:
                        await self._diagnostic("RESPONSE_FINISH_FAILED")

    def _require_connected(self):
        if self._stopping or not self._connected or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        return ResponsePolicy(
            streaming=bool(self._config.get("streaming_enabled")),
            prepare=self._config.get("show_typing", True) is not False,
            send_format=SendFormatPolicy(False, False, True, False, False),
        )

    @staticmethod
    def _target(handle, meta):
        target = decode_reply_target(str(handle))
        session = target["session_id"] if target else str(handle)
        user = target["user_id"] if target else str(handle)
        chat = meta.get("chat_id") or (
            session.split(":", 1)[1]
            if session.startswith("telegram:")
            else user
        )
        if not str(chat).strip():
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        return {
            "chat_id": str(chat),
            "message_thread_id": str(meta.get("message_thread_id") or ""),
            "session_id": str(meta.get("session_id") or session),
            "root_session_id": str(
                meta.get("root_session_id")
                or meta.get("session_id")
                or session,
            ),
            "user_id": str(meta.get("user_id") or user),
            "is_group": "true" if meta.get("is_group") else "false",
        }

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        handle = "telegram:reply:" + uuid.uuid4().hex
        await self._persist_route(
            handle,
            self._target(params["to_handle"], params.get("meta") or {}),
        )
        return {"response_handle": handle}

    async def _message(self, value):
        self._require_connected()
        event_id = value["event_id"]
        handle = (
            "telegram:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        meta = dict(value["meta"])
        session = value["session_id"]
        route = self._target(session, {**meta, "session_id": session})
        for key in ("approval_binding_id", "approval_actor_id"):
            if key in value:
                route[key] = value[key]
        if value.get("event_kind") == "callback":
            route["operator_display"] = meta.get("operator_display", "")
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if created or snapshot.kind.value != "terminal":
            await self._persist_route(handle, route)
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind=value.get("event_kind", "message"),
            conversation={
                "id": meta["chat_id"],
                "type": "group" if meta["is_group"] else "dm",
                "thread_id": str(meta.get("message_thread_id") or "") or None,
            },
            sender_id=value["sender_id"],
            acl_sender_id=value["acl_sender_id"],
            sender_name=meta.get("username") or value["sender_id"],
            content_parts=tuple(value["content_parts"]),
            metadata={
                **meta,
                "session_id": session,
                "user_id": value["user_id"],
                "debounce_key": (
                    event_id
                    if value.get("event_kind") == "callback"
                    else session
                ),
            },
            response_handle=handle,
        )
        return await self._admit_event(event, created) is not None

    async def _callback(self, value):
        return await self._message(value)

    async def _send(self, params, request):
        result = None
        try:
            result = await super()._send(params, request)
            return result
        finally:
            if params.approval is not None and self._platform is not None:
                self._platform.complete_card_delivery(
                    params.delivery_id,
                    result is not None and result["state"] == "acknowledged",
                )

    async def _perform_send(self, params):
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        operation = params.operation.value
        if operation == "message.create":
            if params.approval is not None:
                resource = await platform.send_approval(
                    route,
                    params,
                    self._context.identity,
                )
            elif params.approval_resolution is not None:
                resource = await platform.resolve_approval(route, params)
            else:
                resource = await platform.send_parts(
                    route,
                    params.content_parts,
                    params.content_source,
                )
        elif operation == "stream.start":
            resource = await platform.start_stream(
                route,
                params.stream_type.value,
            )
            resource.update(
                stream_type=params.stream_type.value,
                sequence="0",
                final="false",
            )
        elif operation in {"stream.delta", "stream.end"}:
            ref = self._delivery_resource(
                params.to_handle,
                params.target_delivery_id,
            )
            if ref is None:
                raise TelegramDeliveryError("OUTBOUND_TARGET_UNKNOWN")
            resource = await platform.update_stream(
                dict(ref.attributes),
                params.accumulated_text,
                final=operation == "stream.end",
            )
            resource.update(sequence=str(params.sequence))
            return ResponseResourceRef.create(
                "telegram.delivery",
                params.target_delivery_id,
                resource,
            )
        else:
            raise TelegramDeliveryError("OUTBOUND_OPERATION_UNSUPPORTED")
        return ResponseResourceRef.create(
            "telegram.delivery",
            params.delivery_id,
            resource,
        )

    async def _perform_prepare(self, params):
        await self._require_connected().start_typing(
            params.to_handle,
            self._route_attrs(params.to_handle),
        )
        return None

    def _needs_stream_cleanup(self, ref):
        return dict(ref.attributes).get("stream_type") in {
            "message",
            "reasoning",
        }

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        await self._require_connected().delete_stream(resource)

    async def _release_local_response(self, handle):
        if self._platform is not None:
            await self._platform.stop_typing(handle)

    async def _before_cleanup_complete(self, snapshot):
        if self._platform is not None:
            await self._platform.stop_typing(snapshot.response_handle)
        return snapshot

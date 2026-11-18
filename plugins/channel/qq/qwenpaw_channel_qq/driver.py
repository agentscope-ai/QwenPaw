# -*- coding: utf-8 -*-
"""QQ ownership adapter for the shared response and management protocols."""

from __future__ import annotations

from dataclasses import replace
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

from .errors import QQDeliveryError
from .formatting import (
    _resolve_send_path,
    _route_meta_from_handle,
    resolve_session_id,
)


class QQDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__("qq", "qq.shared.responses", QQDeliveryError)

    @staticmethod
    async def manage(request):
        from .management import manage

        return await manage(request)

    async def start(self, config):
        from .platform import QQPlatform

        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        self._platform = QQPlatform(config, self._message, self._state_changed)
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

    def _require_connected(self):
        if self._stopping or not self._connected or self._platform is None:
            raise QQDeliveryError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        return ResponsePolicy(
            send_format=SendFormatPolicy(False, False, False, False, True),
        )

    @staticmethod
    def _target(handle, meta):
        encoded = decode_reply_target(str(handle))
        session = encoded["session_id"] if encoded else str(handle)
        user = encoded["user_id"] if encoded else str(handle)
        route = {
            k: str(meta.get(k) or "")
            for k in (
                "message_type",
                "sender_id",
                "group_openid",
                "channel_id",
                "guild_id",
                "message_id",
            )
        }
        durable = _route_meta_from_handle(session)
        if durable:
            route.update(durable)
        else:
            route["message_type"] = route["message_type"] or "c2c"
            route["sender_id"] = route["sender_id"] or user
        _resolve_send_path(
            route["message_type"],
            route["sender_id"],
            route["channel_id"],
            route["group_openid"],
            route["guild_id"],
        )
        if any(
            value == "unknown"
            for key, value in route.items()
            if key in {"sender_id", "group_openid", "channel_id", "guild_id"}
        ):
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        route.update(
            session_id=str(
                meta.get("session_id")
                or (
                    session
                    if durable
                    else resolve_session_id(route["sender_id"], route)
                ),
            ),
            user_id=str(meta.get("user_id") or route["sender_id"]),
            is_group=(
                "true"
                if route["message_type"] in {"group", "guild"}
                else "false"
            ),
        )
        route["root_session_id"] = str(
            meta.get("root_session_id") or route["session_id"],
        )
        if "markdown_enabled" in meta:
            route["markdown_enabled"] = str(meta["markdown_enabled"])
        return route

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        handle = "qq:reply:" + uuid.uuid4().hex
        route = self._target(params["to_handle"], params.get("meta") or {})
        route["response_handle"] = handle
        await self._persist_route(handle, route)
        return {"response_handle": handle}

    async def _message(self, value):
        self._require_connected()
        event_id, session = value["event_id"], value["session_id"]
        handle = (
            "qq:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        meta = dict(value["meta"])
        route = self._target(
            session,
            {**meta, "session_id": session, "user_id": value["user_id"]},
        )
        route["response_handle"] = handle
        for key in ("approval_binding_id", "approval_actor_id"):
            if key in value:
                route[key] = value[key]
        if value.get("event_kind") == "callback":
            route["operator_display"] = meta.get("operator_display", "")
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if created or snapshot.kind.value != "terminal":
            await self._persist_route(handle, route)
        kind = route["message_type"]
        conversation_id = {
            "group": route["group_openid"],
            "guild": route["channel_id"],
            "dm": route["guild_id"],
            "c2c": route["sender_id"],
        }[kind]
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind=value.get("event_kind", "message"),
            conversation={
                "id": conversation_id,
                "type": "group" if kind in {"group", "guild"} else "dm",
                "thread_id": None,
            },
            sender_id=value["sender_id"],
            acl_sender_id=value["acl_sender_id"],
            sender_name=meta.get("user_name") or value["sender_id"],
            content_parts=tuple(value["content_parts"]),
            metadata={
                **meta,
                "session_id": session,
                "root_session_id": route["root_session_id"],
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

    async def _record_native(self, params, index, attrs):
        self._routes.record_delivery(
            params.to_handle,
            [
                ResponseResourceRef.create(
                    "qq.native",
                    params.delivery_id + ":" + str(index),
                    attrs,
                ),
            ],
        )
        await self._checkpoint(reserve_bytes=1024)

    async def _perform_send(self, params):
        platform = self._require_connected()
        if params.operation.value != "message.create":
            raise QQDeliveryError("OUTBOUND_OPERATION_UNSUPPORTED")
        route = self._route_attrs(params.to_handle)
        async with platform.delivery(
            params.delivery_id,
            lambda index, attrs: self._record_native(params, index, attrs),
        ):
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
        return ResponseResourceRef.create(
            "qq.delivery",
            params.delivery_id,
            resource,
        )

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

    def _compact_receipt(self, snapshot):
        compact = super()._compact_receipt(snapshot)
        unknown = {ref.resource_id for ref in compact.resource_refs}
        native = tuple(
            ref
            for ref in snapshot.resource_refs
            if ref.kind == "qq.native"
            and dict(ref.attributes).get("delivery_id") in unknown
        )
        return replace(
            compact,
            resource_refs=tuple(
                sorted(
                    (*compact.resource_refs, *native),
                    key=lambda ref: (ref.kind, ref.resource_id),
                ),
            ),
        )

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
    _as_bool,
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
        attrs = self._route_attrs(response_handle)
        return ResponsePolicy(
            # The official stream API covers single chat only, so group,
            # guild and dm routes keep the completed-message path. A C2C
            # stream is a passive reply and needs the inbound ``msg_id`` as
            # its anchor, so routes without one are not streamed either.
            streaming=bool(self._config.get("streaming_enabled"))
            and attrs.get("message_type") == "c2c"
            and bool(attrs.get("message_id")),
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

    @staticmethod
    def _text(params):
        return params.accumulated_text or ""

    async def _perform_stream(self, platform, params):
        """Stream slices use the QQ replace-mode stream_messages API."""
        route = self._route_attrs(params.to_handle)
        markdown = _as_bool(
            route.get(
                "markdown_enabled",
                self._config.get("markdown_enabled", True),
            ),
        )
        stream_type = params.stream_type.value
        text = self._text(params)
        operation = params.operation.value
        if operation == "stream.start":
            # The native stream is opened by the first slice that carries real
            # text, not by ``stream.start``. QQ ``replace`` slices must start
            # with the prefix QQ already delivered (``40007`` otherwise), and
            # the host opens every stream with a placeholder, which no answer
            # extends. Opening lazily also keeps a response that produces no
            # slice from creating an empty message on QQ.
            return ResponseResourceRef.create(
                "qq.delivery",
                params.delivery_id,
                {
                    "stream_type": stream_type,
                    "markdown": "true" if markdown else "false",
                    "sequence": "0",
                    "final": "false",
                },
            )
        ref = self._delivery_resource(
            params.to_handle,
            params.target_delivery_id,
        )
        if ref is None or ref.kind != "qq.delivery":
            raise QQDeliveryError(
                "OUTBOUND_TARGET_UNKNOWN",
                side_effect_possible=False,
            )
        resource = dict(ref.attributes)
        recorded_type = resource.get("stream_type")
        # Resources written before ``stream_type`` was recorded carry no kind
        # to compare, so only an explicit disagreement is rejected.
        if recorded_type is not None and recorded_type != stream_type:
            raise QQDeliveryError(
                "STREAM_TYPE_MISMATCH",
                side_effect_possible=False,
            )
        sequence = params.sequence or 0
        if sequence <= int(resource.get("sequence", "0")):
            raise QQDeliveryError(
                "STREAM_SEQUENCE_STALE",
                side_effect_possible=False,
            )
        final = operation == "stream.end"
        if not resource.get("stream_msg_id"):
            if not text and not final:
                # Nothing to show yet: opening now would deliver a slice the
                # answer cannot extend.
                return ResponseResourceRef.create(
                    "qq.delivery",
                    params.target_delivery_id,
                    resource,
                )
            # The opening slice is the first text QQ ever receives, so it is
            # never a placeholder the later slices would have to rewrite.
            created = await platform.start_stream(route, text, markdown)
            resource.update(created)
            resource.update(sequence=str(sequence), final="false")
            await self._reserve_slice(
                params.to_handle,
                params.target_delivery_id,
                resource,
            )
            if not final:
                return ResponseResourceRef.create(
                    "qq.delivery",
                    params.target_delivery_id,
                    resource,
                )
        if final and not text:
            # QQ rejects an empty closing slice, so keep the delivered text.
            text = str(resource.get("text") or "...")
        # QQ rejects a repeated slice index for one stream. The index is
        # therefore reserved durably before the native call, so a slice whose
        # result is lost locally still consumes it. Replace mode resends the
        # whole text, so continuing from a higher index loses no content,
        # while reusing an index that QQ already accepted would be rejected.
        index = int(resource.get("index", "0")) + 1
        resource.update(index=str(index), text=text)
        await self._reserve_slice(
            params.to_handle,
            params.target_delivery_id,
            resource,
        )
        await platform.update_stream(
            route,
            resource,
            text,
            index=index,
            markdown=markdown,
            final=final,
        )
        # Only an acknowledged slice advances these, so a lost ``stream.end``
        # is archived as unknown evidence instead of a confirmed close.
        resource.update(
            sequence=str(sequence),
            final="true" if final else "false",
        )
        return ResponseResourceRef.create(
            "qq.delivery",
            params.target_delivery_id,
            resource,
        )

    async def _reserve_slice(self, handle, delivery_id, resource):
        """Persist the next slice index before the native call.

        The reservation deliberately leaves ``sequence`` and ``final`` alone:
        only an acknowledged slice advances them. Marking the delivery
        ``unsettled`` is also avoided here, because an unsettled delivery makes
        the shared cleanup skip the stream instead of closing it.
        """
        self._routes.record_delivery(
            handle,
            [
                ResponseResourceRef.create(
                    "qq.delivery",
                    delivery_id,
                    dict(resource),
                ),
            ],
        )
        await self._checkpoint()

    def _needs_stream_cleanup(self, ref):
        # QQ keeps a started stream generating until it sees a slice with
        # ``input_state=10``, so any stream without an acknowledged end slice
        # must be closed by cleanup.
        return bool(dict(ref.attributes).get("stream_msg_id"))

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        attributes = dict(resource)
        # The host sequence is not the QQ slice index; the closing slice must
        # continue the native index, not the response-level sequence.
        await self._require_connected().update_stream(
            {},
            attributes,
            attributes.get("text") or "...",
            index=int(attributes.get("index", "0")) + 1,
            markdown=_as_bool(
                attributes.get(
                    "markdown",
                    self._config.get("markdown_enabled", True),
                ),
            ),
            final=True,
        )

    async def _perform_send(self, params):
        platform = self._require_connected()
        operation = params.operation.value
        if operation in {"stream.start", "stream.delta", "stream.end"}:
            return await self._perform_stream(platform, params)
        if operation != "message.create":
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

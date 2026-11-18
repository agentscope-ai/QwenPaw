# -*- coding: utf-8 -*-
"""Discord host admission and scoped durable response routes."""

from __future__ import annotations

import asyncio
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
from .formatting import resolve_session_id, route_from_handle
from .platform import DiscordDeliveryError, DiscordPlatform


class DiscordDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "discord",
            "discord.shared.responses",
            DiscordDeliveryError,
        )

    async def start(self, config):
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        self._platform = DiscordPlatform(
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
        if self._connected:
            for snapshot in self._routes.pending_cleanups():
                async with self._lock(snapshot.response_handle):
                    try:
                        await self._cleanup(snapshot)
                    except Exception:
                        await self._diagnostic("RESPONSE_FINISH_FAILED")

    def _require_connected(self):
        if not self._connected or self._stopping or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        return ResponsePolicy(
            streaming=bool(self._config.get("streaming_enabled")),
            prepare=True,
            send_format=SendFormatPolicy(False, False),
        )

    @staticmethod
    def _target(handle, meta):
        target = decode_reply_target(str(handle))
        route = route_from_handle(
            target["session_id"] if target else str(handle),
        )
        if route:
            return route
        if meta.get("channel_id"):
            return {"channel_id": str(meta["channel_id"])}
        if meta.get("user_id"):
            return {"user_id": str(meta["user_id"])}
        return {}

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        route = self._target(params["to_handle"], params.get("meta") or {})
        if not route:
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        handle = "discord:reply:" + uuid.uuid4().hex
        native_channel = (params.get("meta") or {}).get("channel_id")
        if native_channel:
            route.update(
                typing_channel_id=str(native_channel),
                stream_channel_id=str(native_channel),
            )
        await self._persist_route(handle, route)
        return {"response_handle": handle}

    async def _message(self, value):
        event_id = value["message_id"]
        handle = (
            "discord:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        meta = dict(value["meta"])
        session = resolve_session_id(value["acl_sender_id"], meta)
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if snapshot is None or snapshot.kind.value != "terminal":
            await self._persist_route(
                handle,
                {
                    **route_from_handle(session),
                    "typing_channel_id": meta["channel_id"],
                    "stream_channel_id": meta["channel_id"],
                },
            )
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind="message",
            conversation={
                "id": meta["channel_id"],
                "type": "group" if meta["is_group"] else "dm",
                "thread_id": meta.get("thread_id"),
            },
            sender_id=value["sender_id"],
            acl_sender_id=value["acl_sender_id"],
            sender_name=value["sender_id"],
            content_parts=tuple(value["content_parts"]),
            metadata={
                **meta,
                "session_id": session,
                "user_id": value["acl_sender_id"],
                "debounce_key": session,
            },
            response_handle=handle,
        )
        return await self._admit_event(event, created) is not None

    async def _perform_send(self, params):
        platform = self._require_connected()
        operation = params.operation.value
        attrs = self._route_attrs(params.to_handle)
        resource_id = params.delivery_id
        if operation == "message.create":
            resource = await platform.send_parts(attrs, params.content_parts)
        elif operation == "stream.start":
            if not self._config.get("streaming_enabled"):
                raise DiscordDeliveryError("STREAMING_UNSUPPORTED")
            resource = await platform.start_stream(
                (
                    {"channel_id": attrs["stream_channel_id"]}
                    if attrs.get("stream_channel_id")
                    else attrs
                ),
                params.accumulated_text,
            )
            if attrs.get("user_id"):
                resource["replacement_user_id"] = attrs["user_id"]
            resource.update(
                sequence="0",
                text=params.accumulated_text,
                final="false",
                stream_type=params.stream_type.value,
            )
        elif operation in {"stream.delta", "stream.end"}:
            ref = self._delivery_resource(
                params.to_handle,
                params.target_delivery_id,
            )
            if ref is None:
                raise DiscordDeliveryError("OUTBOUND_TARGET_UNKNOWN")
            resource = dict(ref.attributes)
            if params.stream_type.value != resource.get("stream_type"):
                raise DiscordDeliveryError("STREAM_TYPE_MISMATCH")
            if params.sequence <= int(resource.get("sequence", "0")):
                raise DiscordDeliveryError("STREAM_SEQUENCE_STALE")
            # Once any edit result is unknown, a different delivery ID cannot
            # use the same placeholder to repeat or replace its effects.
            snapshot = self._routes.snapshot(params.to_handle)
            if any(
                ref.kind == "discord.attempt"
                and dict(ref.attributes).get("target_delivery_id")
                == params.target_delivery_id
                and dict(ref.attributes).get("state") == "unknown"
                and ref.resource_id != params.delivery_id
                for ref in snapshot.resource_refs
            ):
                raise DiscordDeliveryError(
                    "STREAM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                )
            final = operation == "stream.end"
            try:
                updated = await platform.update_stream(
                    resource,
                    params.accumulated_text,
                    final=final,
                )
            except (DiscordDeliveryError, asyncio.CancelledError) as exc:
                if (
                    isinstance(exc, asyncio.CancelledError)
                    or exc.side_effect_possible
                ):
                    resource["unsettled"] = "true"
                    self._routes.record_delivery(
                        params.to_handle,
                        [
                            ResponseResourceRef.create(
                                "discord.delivery",
                                params.target_delivery_id,
                                resource,
                            ),
                        ],
                    )
                raise
            resource.update(
                updated,
                sequence=str(params.sequence),
                text=params.accumulated_text,
                final="true" if final else "false",
            )
            resource_id = params.target_delivery_id
        else:
            raise DiscordDeliveryError("OPERATION_UNSUPPORTED")
        return ResponseResourceRef.create(
            "discord.delivery",
            resource_id,
            resource,
        )

    async def _perform_prepare(self, params):
        platform = self._require_connected()
        attrs = self._route_attrs(params.to_handle)
        await platform.start_typing(
            params.to_handle,
            (
                {"channel_id": attrs["typing_channel_id"]}
                if attrs.get("typing_channel_id")
                else attrs
            ),
        )
        return ResponseResourceRef.create(
            "discord.delivery",
            params.delivery_id,
            {"typing": "true"},
        )

    def _needs_stream_cleanup(self, ref):
        resource = dict(ref.attributes)
        needs = (
            bool(resource.get("stream_type"))
            and resource.get("final") != "true"
        )
        if needs:
            self._require_connected()
        return needs

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        platform = self._require_connected()
        await platform.update_stream(
            resource,
            resource.get("text") or "...",
            final=True,
        )

    async def _cleanup(self, snapshot):
        try:
            return await super()._cleanup(snapshot)
        except BaseException:
            # An unresolved native message must retain its unknown receipt,
            # while the cancelled response still releases its local typing.
            if self._platform is not None:
                try:
                    await self._platform.stop_typing(snapshot.response_handle)
                except BaseException:
                    try:
                        await self._diagnostic("TYPING_STOP_FAILED")
                    except BaseException:
                        # Preserve the original response error/cancellation
                        # even when its closing peer cannot accept diagnostics.
                        pass
            raise

    async def _release_local_response(self, handle):
        if self._platform is not None:
            await self._platform.stop_typing(handle)

    async def _before_cleanup_complete(self, snapshot):
        if self._platform is not None:
            await self._platform.stop_typing(snapshot.response_handle)
        return snapshot

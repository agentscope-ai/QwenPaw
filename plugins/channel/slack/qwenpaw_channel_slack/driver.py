# -*- coding: utf-8 -*-
"""Slack admission and response effects over the shared worker protocol."""

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
from .platform import SlackPlatform
from .sender import SlackSender
from .utils import SlackDeliveryError


class SlackDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__("slack", "slack.shared.responses", SlackDeliveryError)

    async def start(self, config):
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        self._platform = SlackPlatform(
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
        if self._connected != (state == "connected"):
            self._connection_generation += 1
        self._connected = state == "connected"
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
            send_format=SendFormatPolicy(
                direct_prefix=False,
                parts_configured_prefix=False,
                parts_metadata_prefix=False,
                stream_prefix=False,
                parts_strip_text=False,
            ),
        )

    @staticmethod
    def _target(handle, meta):
        target = decode_reply_target(str(handle))
        to_handle = (
            (target["session_id"] or target["user_id"])
            if target
            else str(handle)
        )
        channel, thread = SlackSender.resolve_route(to_handle, meta)
        return {
            "channel_id": channel,
            "thread_ts": thread or "",
            "stream_channel_id": meta.get("slack_channel_id") or "",
        }

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        route = self._target(params["to_handle"], params.get("meta") or {})
        if not route["channel_id"]:
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        handle = "slack:reply:" + uuid.uuid4().hex
        await self._persist_route(handle, route)
        return {"response_handle": handle}

    async def _message(self, value):
        event_id = value["event_id"]
        handle = (
            "slack:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        meta = dict(value["meta"])
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if snapshot is None or snapshot.kind.value != "terminal":
            await self._persist_route(
                handle,
                self._target(value["session_id"], meta),
            )
        session = value["session_id"]
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind="message",
            conversation={
                "id": meta["slack_channel_id"],
                "type": "group" if meta["is_group"] else "dm",
                "thread_id": meta.get("slack_thread_ts") or None,
            },
            sender_id=value["sender_id"],
            acl_sender_id=value["acl_sender_id"],
            sender_name=meta.get("user_name") or value["sender_id"],
            content_parts=tuple(value["content_parts"]),
            metadata={
                **meta,
                "session_id": session,
                "user_id": value["user_id"],
                "debounce_key": session,
                **(
                    {"file_extraction_error": True}
                    if value.get("file_extraction_error")
                    else {}
                ),
            },
            response_handle=handle,
        )
        return await self._admit_event(event, created) is not None

    async def _perform_send(self, params):
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        operation = params.operation.value
        resource_id = params.delivery_id
        if operation == "message.create":
            resource = await platform.send_parts(route, params.content_parts)
        elif operation == "stream.start":
            if not self._config.get("streaming_enabled"):
                raise SlackDeliveryError("STREAMING_UNSUPPORTED")
            resource = await platform.start_stream(
                route,
                params.stream_type.value,
            )
            resource.update(
                thread_ts=route["thread_ts"],
                sequence="0",
                text=resource.get("text", params.accumulated_text),
                final=resource.get("final", "false"),
                stream_type=params.stream_type.value,
            )
        elif operation in {"stream.delta", "stream.end"}:
            ref = self._delivery_resource(
                params.to_handle,
                params.target_delivery_id,
            )
            if ref is None:
                raise SlackDeliveryError("OUTBOUND_TARGET_UNKNOWN")
            resource = dict(ref.attributes)
            if params.stream_type.value != resource.get("stream_type"):
                raise SlackDeliveryError("STREAM_TYPE_MISMATCH")
            if params.sequence <= int(resource.get("sequence", "0")):
                raise SlackDeliveryError("STREAM_SEQUENCE_STALE")
            snapshot = self._routes.snapshot(params.to_handle)
            if any(
                attempt.kind == "slack.attempt"
                and dict(attempt.attributes).get("target_delivery_id")
                == params.target_delivery_id
                and dict(attempt.attributes).get("state") == "unknown"
                and attempt.resource_id != params.delivery_id
                for attempt in snapshot.resource_refs
            ):
                raise SlackDeliveryError(
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
            except (SlackDeliveryError, asyncio.CancelledError) as exc:
                if (
                    isinstance(exc, asyncio.CancelledError)
                    or exc.side_effect_possible
                ):
                    resource["unsettled"] = "true"
                    self._routes.record_delivery(
                        params.to_handle,
                        [
                            ResponseResourceRef.create(
                                "slack.delivery",
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
                final="true" if final else resource.get("final", "false"),
            )
            resource_id = params.target_delivery_id
        else:
            raise SlackDeliveryError("OPERATION_UNSUPPORTED")
        return ResponseResourceRef.create(
            "slack.delivery",
            resource_id,
            resource,
        )

    def _needs_stream_cleanup(self, ref):
        resource = dict(ref.attributes)
        needed = (
            bool(resource.get("stream_type"))
            and resource.get("final") != "true"
        )
        if needed:
            self._require_connected()
        return needed

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        await self._require_connected().update_stream(
            resource,
            resource.get("text") or "...",
            final=True,
        )

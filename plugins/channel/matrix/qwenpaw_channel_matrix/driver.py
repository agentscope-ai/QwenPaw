# -*- coding: utf-8 -*-
"""Matrix routes and effects over the existing shared response journal."""

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

from .errors import MatrixDeliveryError


class MatrixDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "matrix",
            "matrix.shared.responses",
            MatrixDeliveryError,
        )

    async def start(self, config):
        if self._platform is not None:
            raise RuntimeError("MATRIX_RESOURCES_ALREADY_OWNED")
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        if not self._config.get("enabled", True):
            await self._state_changed("disconnected")
            return
        from .platform import MatrixPlatform

        self._platform = MatrixPlatform(
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
            async with self._lock(snapshot.response_handle):
                try:
                    await self._cleanup(snapshot)
                except Exception:
                    await self._diagnostic("MATRIX_RESPONSE_CLEANUP_PENDING")

    def _require_connected(self):
        if self._stopping or not self._connected or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        return ResponsePolicy(
            streaming=bool(self._config.get("streaming_enabled", False)),
            prepare=True,
            send_format=SendFormatPolicy(False, False, True, False, True),
            continue_on_delivery_error=True,
        )

    @staticmethod
    def _target(handle, meta):
        target = decode_reply_target(str(handle))
        session = target["session_id"] if target else str(handle)
        fallback = target["user_id"] if target else session
        room = meta.get("room_id") or (
            session[len("matrix:") :]
            if session.startswith("matrix:")
            else fallback
        )
        if not isinstance(room, str) or not room.strip():
            raise MatrixDeliveryError("OUTBOUND_TARGET_UNKNOWN")
        return {
            "room_id": room,
            "sender_id": str(meta.get("sender_id") or ""),
            "user_id": str(
                meta.get("user_id") or (target["user_id"] if target else ""),
            ),
        }

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        handle = "matrix:reply:" + uuid.uuid4().hex
        await self._persist_route(
            handle,
            self._target(params["to_handle"], params.get("meta") or {}),
        )
        return {"response_handle": handle}

    async def _message(self, payload):
        self._require_connected()
        meta = dict(payload["meta"])
        room_id, sender_id = meta["room_id"], payload["sender_id"]
        native_event_id = meta["event_id"]
        if not isinstance(native_event_id, str) or not native_event_id:
            raise ValueError("MATRIX_EVENT_ID_REQUIRED")
        handle = (
            "matrix:reply:"
            + hashlib.sha256(
                (
                    self._context.identity.instance_id + ":" + native_event_id
                ).encode(),
            ).hexdigest()
        )
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        route = self._target(room_id, meta)
        if created or snapshot.kind.value != "terminal":
            await self._persist_route(handle, route)
        session_id = "matrix:" + room_id
        user_id = (
            sender_id
            if meta["is_group"]
            and not self._config.get("share_session_in_group", True)
            else room_id
        )
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=native_event_id,
            event_kind="message",
            conversation={
                "id": room_id,
                "type": "dm" if meta["is_dm"] else "group",
                "thread_id": None,
            },
            sender_id=sender_id,
            acl_sender_id=payload["acl_sender_id"],
            sender_name=meta.get("user_name") or sender_id,
            content_parts=tuple(
                self._wire_part(part) for part in payload["content_parts"]
            ),
            metadata={
                **meta,
                "user_id": user_id,
                "session_id": session_id,
                "debounce_key": session_id,
                # Matrix already applied per-room mention rules. The
                # host still evaluates ACL using the real sender.
                "bot_mentioned": True,
            },
            response_handle=handle,
        )
        admitted = await self._admit_event(event, created)
        return (
            admitted is not None
            and native_event_id in admitted[0].accepted_event_ids
        )

    @staticmethod
    def _wire_part(part):
        value = (
            part.model_dump(mode="json", exclude_none=True)
            if hasattr(part, "model_dump")
            else dict(part)
        )
        kind = value["type"]
        locator = (
            "text"
            if kind == "text"
            else "data"
            if kind == "audio"
            else kind + "_url"
        )
        return {
            key: value[key]
            for key in ("type", locator, "filename", "mime_type", "format")
            if key in value and value[key] is not None
        }

    def _assert_stream_settled(self, handle, target, *, exclude=None):
        snapshot = self._routes.snapshot(handle)
        if any(
            ref.kind == "matrix.attempt"
            and ref.resource_id != exclude
            and dict(ref.attributes).get("target_delivery_id") == target
            and dict(ref.attributes).get("state") == "unknown"
            for ref in snapshot.resource_refs
        ):
            raise MatrixDeliveryError(
                "MATRIX_STREAM_UNSETTLED",
                side_effect_possible=True,
            )

    async def _perform_send(self, params):
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        async with platform.operation():
            operation = params.operation.value
            if operation == "message.create":
                receipt = await platform.send_parts(
                    route,
                    params.content_parts,
                    params.content_source,
                    params.delivery_id,
                )
            elif operation == "stream.start":
                receipt = await platform.start_stream(
                    route,
                    params.stream_type.value,
                    params.delivery_id,
                )
            elif operation in {"stream.delta", "stream.end"}:
                ref = self._delivery_resource(
                    params.to_handle,
                    params.target_delivery_id,
                )
                if ref is None or not dict(ref.attributes).get("event_id"):
                    raise MatrixDeliveryError("OUTBOUND_TARGET_UNKNOWN")
                receipt = dict(ref.attributes)
                if (
                    receipt["room_id"] != route["room_id"]
                    or receipt.get("stream_type") != params.stream_type.value
                ):
                    raise MatrixDeliveryError("MATRIX_STREAM_TARGET_CONFLICT")
                self._assert_stream_settled(
                    params.to_handle,
                    ref.resource_id,
                    exclude=params.delivery_id,
                )
                if receipt.get("unsettled") == "true":
                    raise MatrixDeliveryError(
                        "MATRIX_STREAM_UNSETTLED",
                        side_effect_possible=True,
                    )
                if receipt.get("final") == "true" or params.sequence <= int(
                    receipt.get("sequence", "0"),
                ):
                    raise MatrixDeliveryError(
                        "MATRIX_STREAM_SEQUENCE_CONFLICT",
                    )
                receipt["unsettled"] = "true"
                self._routes.record_delivery(
                    params.to_handle,
                    [
                        ResponseResourceRef.create(
                            "matrix.delivery",
                            ref.resource_id,
                            receipt,
                        ),
                    ],
                )
                await self._checkpoint()
                try:
                    receipt = await platform.update_stream(
                        receipt,
                        params.accumulated_text or "",
                        params.delivery_id,
                        final=operation == "stream.end",
                    )
                except MatrixDeliveryError as exc:
                    if not exc.side_effect_possible:
                        receipt["unsettled"] = "false"
                        self._routes.record_delivery(
                            params.to_handle,
                            [
                                ResponseResourceRef.create(
                                    "matrix.delivery",
                                    ref.resource_id,
                                    receipt,
                                ),
                            ],
                        )
                        await self._checkpoint()
                    raise
                if receipt.get("suppressed") == "true":
                    await platform.stop_typing(
                        params.to_handle,
                        route["room_id"],
                    )
                receipt.update(
                    sequence=str(params.sequence),
                    unsettled="false",
                    owner=params.to_handle,
                )
                return ResponseResourceRef.create(
                    "matrix.delivery",
                    ref.resource_id,
                    receipt,
                )
            else:
                raise MatrixDeliveryError("OUTBOUND_OPERATION_UNSUPPORTED")
        if receipt.get("suppressed") == "true":
            async with platform.operation():
                await platform.stop_typing(params.to_handle, route["room_id"])
        receipt["owner"] = params.to_handle
        return ResponseResourceRef.create(
            "matrix.delivery",
            params.delivery_id,
            receipt,
        )

    async def _perform_prepare(self, params):
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        receipt = {
            "typing": "true",
            "owner": params.to_handle,
            "room_id": route["room_id"],
            "final": "false",
        }
        ref = ResponseResourceRef.create(
            "matrix.delivery",
            params.delivery_id,
            receipt,
        )
        self._routes.record_delivery(params.to_handle, [ref])
        await self._checkpoint()
        async with platform.operation():
            await platform.start_typing(params.to_handle, route)
        return ref

    def _needs_stream_cleanup(self, ref):
        attrs = dict(ref.attributes)
        return attrs.get("typing") == "true" or attrs.get("stream_type") in {
            "message",
            "reasoning",
        }

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        if resource.get("typing") == "true":
            platform = self._require_connected()
            async with platform.operation():
                await platform.stop_typing(
                    resource["owner"],
                    resource["room_id"],
                )
        else:
            # Last acknowledged edit remains the visible message. Closing a
            # response has no additional Matrix edit effect to replay.
            self._assert_stream_settled(resource["owner"], ref.resource_id)

    async def _release_local_response(self, handle):
        if self._platform is not None:
            await self._platform.stop_typing(handle, local_only=True)

    def _compact_receipt(self, snapshot):
        compact = super()._compact_receipt(snapshot)
        if any(
            dict(ref.attributes).get("state") == "unknown"
            for ref in compact.resource_refs
        ):
            return replace(
                compact,
                resource_refs=tuple(
                    sorted(
                        (
                            *compact.resource_refs,
                            *(
                                ref
                                for ref in snapshot.resource_refs
                                if ref.kind == "matrix.delivery"
                                and ref not in compact.resource_refs
                                and dict(ref.attributes).get("unsettled")
                                == "true"
                            ),
                        ),
                    ),
                ),
            )
        return compact

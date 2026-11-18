# -*- coding: utf-8 -*-
"""WeCom adapter over the shared admission, receipt and response lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
import uuid

from qwenpaw.channel_protocol.models import InboundEvent
from qwenpaw.channel_protocol.response_lifecycle import (
    ResponseCleanupState,
    ResponseResourceRef,
)
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.channel_protocol.targets import decode_reply_target

from .errors import WeComDeliveryError
from .inbound import parse_chatid_from_handle, resolve_session_id


class WeComDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__("wecom", "wecom.shared.responses", WeComDeliveryError)
        self._native_recovery_lock = asyncio.Lock()

    @staticmethod
    async def manage(request):
        from .management import manage

        return await manage(request)

    async def start(self, config):
        from .platform import WeComPlatform

        if self._platform is not None:
            raise RuntimeError("PLATFORM_ALREADY_STARTED")
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        self._platform = WeComPlatform(
            config,
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
        generation = self._connection_generation
        if connected:
            async with self._native_recovery_lock:
                self._check_connection(generation)
                await self._context.set_platform_state(state)
                for pending in self._routes.pending_cleanups():
                    self._check_connection(generation)
                    async with self._lock(pending.response_handle):
                        self._check_connection(generation)
                        snapshot = self._routes.snapshot(
                            pending.response_handle,
                        )
                        if snapshot is None or not self._expired_native(
                            snapshot,
                        ):
                            continue
                        try:
                            await self._cleanup(snapshot)
                        except Exception:
                            await self._diagnostic("RESPONSE_FINISH_FAILED")
        else:
            await self._context.set_platform_state(state)

    def _require_connected(self):
        if self._stopping or not self._connected or self._platform is None:
            raise WeComDeliveryError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        return ResponsePolicy(
            streaming=bool(self._config.get("streaming_enabled", False)),
            prepare=True,
            send_format=SendFormatPolicy(False, False, False, False, False),
        )

    @staticmethod
    def _target(handle, meta):
        encoded = decode_reply_target(str(handle))
        session = (
            (encoded["session_id"] or encoded["user_id"])
            if encoded
            else str(handle)
        )
        chatid = str(
            meta.get("wecom_chatid") or parse_chatid_from_handle(session),
        )
        if not chatid or chatid == "unknown":
            raise WeComDeliveryError("OUTBOUND_TARGET_UNKNOWN")
        chat_type = str(
            meta.get("wecom_chat_type")
            or ("group" if session.startswith("wecom:group:") else "single"),
        )
        sender = str(
            meta.get("wecom_sender_id")
            or (encoded["user_id"] if encoded else "")
            or chatid,
        )
        route = {
            "wecom_chatid": chatid,
            "wecom_chat_type": chat_type,
            "wecom_sender_id": sender,
            "session_id": str(
                meta.get("session_id")
                or session
                or resolve_session_id(sender, meta),
            ),
        }
        if isinstance(meta.get("bot_prefix"), str):
            route["bot_prefix"] = meta["bot_prefix"]
        return route

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        handle = "wecom:reply:" + uuid.uuid4().hex
        route = self._target(params["to_handle"], params.get("meta") or {})
        route["response_handle"] = handle
        await self._persist_route(handle, route)
        return {"response_handle": handle}

    async def _message(self, value):
        generation = self._connection_generation
        event_id, session = value["event_id"], value["session_id"]
        handle = (
            "wecom:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        meta = dict(value["meta"])
        route = self._target(session, {**meta, "session_id": session})
        route["response_handle"] = handle
        for key in ("approval_binding_id", "approval_actor_id"):
            if key in value:
                route[key] = value[key]
        async with self._native_recovery_lock:
            self._check_connection(generation)
            platform = self._require_connected()
            snapshot = self._routes.snapshot(handle)
            created = snapshot is None
            if snapshot is not None and snapshot.kind.value == "terminal":
                return True
            if created:
                route.update(platform.register_frame(handle, value["frame"]))
                try:
                    await self._persist_route(handle, route)
                except BaseException:
                    await platform.release_route(handle)
                    raise
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind=value.get("event_kind", "message"),
            conversation={
                "id": route["wecom_chatid"],
                "type": "group" if meta.get("is_group") else "dm",
                "thread_id": None,
            },
            sender_id=value["sender_id"],
            acl_sender_id=value["acl_sender_id"],
            sender_name=meta.get("user_name") or value["sender_id"],
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

    def _processing_refs(self, handle):
        return [
            ref
            for ref in self._routes.snapshot(handle).resource_refs
            if ref.kind == "wecom.delivery"
            and dict(ref.attributes).get("role") == "processing"
            and dict(ref.attributes).get("final") != "true"
        ]

    async def _mark_processing(self, handle, *, final):
        refs = self._processing_refs(handle)
        if refs:
            self._routes.record_delivery(
                handle,
                [
                    ResponseResourceRef.create(
                        "wecom.delivery",
                        ref.resource_id,
                        {
                            **dict(ref.attributes),
                            "unsettled": "false" if final else "true",
                            "final": "true" if final else "false",
                        },
                    )
                    for ref in refs
                ],
            )
            await self._checkpoint()

    @asynccontextmanager
    async def _processing_handoff(self, handle):
        previous = self._processing_refs(handle)
        await self._mark_processing(handle, final=False)
        try:
            yield
        except WeComDeliveryError as exc:
            if not exc.side_effect_possible and previous:
                self._routes.record_delivery(handle, previous)
                await self._checkpoint()
            raise
        else:
            await self._mark_processing(handle, final=True)

    async def _perform_prepare(self, params):
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        async with platform.delivery():
            if platform._frame(route) is None:
                return None
            sid = uuid.uuid4().hex
            provisional = {
                **route,
                "stream_id": sid,
                "text": "🤔 Thinking...",
                "role": "processing",
                "final": "false",
                "unsettled": "true",
            }
            self._routes.record_delivery(
                params.to_handle,
                [
                    ResponseResourceRef.create(
                        "wecom.delivery",
                        params.delivery_id,
                        provisional,
                    ),
                ],
            )
            await self._checkpoint()
            try:
                resource = await platform.prepare(route, sid)
            except WeComDeliveryError as exc:
                if not exc.side_effect_possible:
                    self._routes.record_delivery(
                        params.to_handle,
                        [
                            ResponseResourceRef.create(
                                "wecom.delivery",
                                params.delivery_id,
                                {
                                    **provisional,
                                    "unsettled": "false",
                                    "final": "true",
                                },
                            ),
                        ],
                    )
                    await self._checkpoint()
                raise
        resource["unsettled"] = "false"
        return ResponseResourceRef.create(
            "wecom.delivery",
            params.delivery_id,
            resource,
        )

    async def _perform_send(self, params):
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        operation = params.operation.value
        resource_id = params.delivery_id
        async with platform.delivery():
            if operation == "message.create":
                async with self._processing_handoff(params.to_handle):
                    if params.approval is not None:
                        resource = await platform.send_approval(
                            route,
                            params,
                            self._context.identity,
                        )
                    elif params.approval_resolution is not None:
                        resource = await platform.resolve_approval(
                            route,
                            params,
                        )
                    else:
                        resource = await platform.send_parts(
                            route,
                            params.content_parts,
                            params.content_source,
                        )
            elif operation == "stream.start":
                if not self._config.get("streaming_enabled", False):
                    raise WeComDeliveryError("STREAMING_UNSUPPORTED")
                async with self._processing_handoff(params.to_handle):
                    resource = await platform.start_stream(
                        route,
                        params.stream_type.value,
                        params.accumulated_text,
                    )
                    self._routes.record_delivery(
                        params.to_handle,
                        [
                            ResponseResourceRef.create(
                                "wecom.delivery",
                                resource_id,
                                {**resource, "unsettled": "true"},
                            ),
                        ],
                    )
                    await self._checkpoint()
                    if params.accumulated_text:
                        await platform.update_stream(
                            resource,
                            params.accumulated_text,
                            final=False,
                        )
                    resource["unsettled"] = "false"
            elif operation in {"stream.delta", "stream.end"}:
                ref = self._delivery_resource(
                    params.to_handle,
                    params.target_delivery_id,
                )
                if ref is None:
                    raise WeComDeliveryError("OUTBOUND_TARGET_UNKNOWN")
                resource = dict(ref.attributes)
                if resource.get("stream_type") != params.stream_type.value:
                    raise WeComDeliveryError("STREAM_TYPE_MISMATCH")
                if resource.get("final") == "true" or params.sequence <= int(
                    resource.get("sequence", "0"),
                ):
                    raise WeComDeliveryError("STREAM_SEQUENCE_STALE")
                snapshot = self._routes.snapshot(params.to_handle)
                if resource.get("unsettled") == "true" or any(
                    attempt.kind == "wecom.attempt"
                    and dict(attempt.attributes).get("target_delivery_id")
                    == params.target_delivery_id
                    and dict(attempt.attributes).get("state") == "unknown"
                    and attempt.resource_id != params.delivery_id
                    for attempt in snapshot.resource_refs
                ):
                    raise WeComDeliveryError(
                        "STREAM_RESULT_UNKNOWN",
                        side_effect_possible=True,
                    )
                final = operation == "stream.end"
                try:
                    await platform.update_stream(
                        resource,
                        params.accumulated_text,
                        final=final,
                    )
                except (WeComDeliveryError, asyncio.CancelledError) as exc:
                    if (
                        isinstance(exc, asyncio.CancelledError)
                        or exc.side_effect_possible
                    ):
                        self._routes.record_delivery(
                            params.to_handle,
                            [
                                ResponseResourceRef.create(
                                    "wecom.delivery",
                                    params.target_delivery_id,
                                    {**resource, "unsettled": "true"},
                                ),
                            ],
                        )
                    raise
                resource.update(
                    text=params.accumulated_text,
                    sequence=str(params.sequence),
                    final="true" if final else "false",
                )
                resource_id = params.target_delivery_id
            else:
                raise WeComDeliveryError("OUTBOUND_OPERATION_UNSUPPORTED")
        return ResponseResourceRef.create(
            "wecom.delivery",
            resource_id,
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

    def _needs_stream_cleanup(self, ref):
        return bool(dict(ref.attributes).get("stream_id"))

    def _expired_native(self, snapshot):
        if (
            self._platform is None
            or self._stopping
            or snapshot.cleanup_state is not ResponseCleanupState.PENDING
        ):
            return None
        for ref in snapshot.route_refs:
            if (
                ref.kind != "wecom.route"
                or ref.resource_id != snapshot.response_handle
            ):
                continue
            route = dict(ref.attributes)
            if route.get("response_handle") != snapshot.response_handle:
                continue
            reason = self._platform.native_route_expiry(route)
            if reason:
                return route, reason
        return None

    async def _cleanup(self, snapshot):
        expired = self._expired_native(snapshot)
        if expired is None:
            try:
                return await super()._cleanup(snapshot)
            except Exception:
                # A reconnect may invalidate the target after the first check.
                snapshot = self._routes.snapshot(snapshot.response_handle)
                if snapshot is None or not self._expired_native(snapshot):
                    raise
                return await self._cleanup(snapshot)
        handle = snapshot.response_handle
        platform = self._platform
        async with platform.delivery():
            if await self._archived(handle):
                await self._retire_archived(handle)
                return
            route, reason = expired
            if not any(
                ref.kind == "wecom.retirement"
                for ref in snapshot.resource_refs
            ):
                receipt_id = handle + ":native-retirement"
                while any(
                    ref.kind == "wecom.attempt"
                    and ref.resource_id == receipt_id
                    for ref in snapshot.resource_refs
                ):
                    receipt_id += ":local"
                context = {
                    **route,
                    "reason_code": reason,
                    "cleanup": "local_only",
                }
                evidence = (
                    ResponseResourceRef.create(
                        "wecom.retirement",
                        handle,
                        context,
                    ),
                    ResponseResourceRef.create(
                        "wecom.attempt",
                        receipt_id,
                        {
                            "operation": "response.cleanup",
                            "state": "unknown",
                            "reason_code": reason,
                            "fingerprint": hashlib.sha256(
                                json.dumps(context, sort_keys=True).encode(),
                            ).hexdigest(),
                        },
                    ),
                )
                snapshot = replace(
                    snapshot,
                    version=snapshot.version + 1,
                    resource_refs=tuple(
                        sorted((*snapshot.resource_refs, *evidence)),
                    ),
                )
                self._routes.restore(snapshot)
            await self._checkpoint()
            await platform.cleanup_resource(route, local_only=True)
            candidate = self._compact_receipt(
                self._routes.cleanup_candidate(handle, snapshot.outcome),
            )
            try:
                await self._archive(candidate)
            finally:
                # A durable archive may precede a failed live checkpoint write.
                if self._routes.snapshot(handle) is None:
                    await platform.release_route(handle, local_only=True)

    async def _retire_archived(self, handle):
        if self._platform is not None:
            async with self._platform.delivery():
                await self._platform.release_route(handle, local_only=True)
        await super()._retire_archived(handle)

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        platform = self._require_connected()
        async with platform.delivery():
            await platform.cleanup_resource(resource)

    async def _before_cleanup_complete(self, snapshot):
        if self._platform is not None:
            await self._platform.release_route(snapshot.response_handle)
        return snapshot

    def _compact_receipt(self, snapshot):
        compact = super()._compact_receipt(snapshot)
        if any(
            ref.kind == "wecom.retirement" for ref in snapshot.resource_refs
        ):
            return replace(
                compact,
                resource_refs=tuple(
                    sorted(
                        (
                            replace(ref, kind="wecom.receipt")
                            if ref.kind == "wecom.attempt"
                            and dict(ref.attributes).get("state") != "unknown"
                            else ref
                        )
                        for ref in snapshot.resource_refs
                    ),
                ),
            )
        # Ephemeral native targets cannot be reconstructed after reconnect/restart.
        # Unknown stream references remain evidence, never a replay instruction.
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
                                if ref.kind == "wecom.delivery"
                                and ref not in compact.resource_refs
                                and dict(ref.attributes).get("unsettled")
                                == "true"
                            ),
                        ),
                    ),
                ),
            )
        return compact

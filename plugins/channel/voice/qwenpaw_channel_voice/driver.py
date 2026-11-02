# -*- coding: utf-8 -*-
"""Twilio calls and turns over the existing shared response journal."""

from __future__ import annotations

import hashlib
import logging
import uuid

from qwenpaw.channel_protocol.models import (
    ContentSource,
    EndpointParams,
    InboundEvent,
)
from qwenpaw.channel_protocol.response_lifecycle import (
    ResponseResourceRef,
    ResponseRouteKind,
)
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.channel_protocol.targets import decode_reply_target

from .platform import VoicePlatform, VoicePlatformError

logger = logging.getLogger(__name__)
_MAX_PENDING_TURNS_PER_CALL = 8


class VoiceDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "voice",
            "voice.shared.responses",
            VoicePlatformError,
            extra_rpc_pressure_reasons=("TEMPORARY_UNAVAILABLE",),
        )

    async def start(self, config):
        if self._platform is not None:
            raise RuntimeError("VOICE_RESOURCES_ALREADY_OWNED")
        self._config = dict(config)
        token = self._config.pop("twilio_auth_token", "")
        self._stopping = False
        await self._restore_responses()
        if not config.get("enabled", False):
            await self._state_changed("disconnected")
            return
        platform = VoicePlatform()
        self._platform = platform
        await self._state_changed("connecting")
        try:
            await platform.prepare(self._config, {"twilio_auth_token": token})
            await platform.start(
                self._handle_native_event,
                self._endpoint,
                self._context.identity.generation,
            )
            platform.confirm_startup()
            await self._state_changed("connected")
            platform.complete_startup()
        except BaseException:
            self._connected = False
            platform.mark_startup_failed("VOICE_STARTUP_FAILED")
            await platform.abort_startup("VOICE_STARTUP_FAILED")
            await self._state_changed("failed")
            raise

    async def _state_changed(self, state):
        connected = state == "connected" and not self._stopping
        if connected != self._connected:
            self._connection_generation += 1
        self._connected = connected
        await self._context.set_platform_state(state)

    async def _endpoint(self, operation, endpoint):
        identity = self._context.identity.to_mapping()
        if operation == "unregister":
            result = await self._context.peer.call(
                "ingress.endpoint.unregister",
                identity,
            )
            expected = {
                "status": "unregistered",
                "generation": identity["generation"],
            }
        else:
            params = EndpointParams.from_mapping(
                {
                    **identity,
                    "protocol": "http+ws",
                    "host": endpoint.host,
                    "port": endpoint.port,
                    "path": "/voice",
                    "public_base_url": endpoint.public_base_url,
                    "readiness": endpoint.readiness,
                    "bound_externally": endpoint.bound_externally,
                    "auth_required": True,
                    "quiescing": False,
                },
            )
            result = await self._context.peer.call(
                "ingress.endpoint." + operation,
                params.to_mapping(),
            )
            expected = {
                "status": (
                    "registered" if operation == "register" else "updated"
                ),
                "generation": identity["generation"],
                "readiness": endpoint.readiness,
            }
        if not isinstance(result, dict) or any(
            result.get(k) != v for k, v in expected.items()
        ):
            raise VoicePlatformError("VOICE_ENDPOINT_ACK_INVALID")
        if operation != "unregister":
            # A1 without A3 forwarding is deliberately insufficient. No direct
            # child tunnel, guessed API port or substitute owner registry.
            if operation == "register" or "forwarding" in result:
                self._platform.set_forwarding(result.get("forwarding"))

    def _require_connected(self):
        if self._stopping or not self._connected or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        self._stopping = True
        self._connected = False
        self._connection_generation += 1
        platform = self._platform
        if platform is not None:
            await platform.close()
            if not platform.cleanup_complete:
                raise VoicePlatformError("VOICE_STOP_INCOMPLETE")
            self._platform = None
        await self._context.set_platform_state("disconnected")

    def response_policy(self, response_handle):
        # VoiceConfig has no token-delta streaming switch. Completed messages
        # retain immediate token+last output; direct sends retain one final.
        return ResponsePolicy(
            send_format=SendFormatPolicy(False, False, True, False, True),
            raw_completed_text="content",
        )

    def _route(self, connection, turn):
        return {
            "binding": connection.session_binding,
            "connection_id": connection.connection_id,
            "call_sid": connection.platform_session_id,
            "caller": connection.from_number,
            "turn_id": str(turn),
            "generation": str(connection.generation),
        }

    def _admit_turn(self, binding):
        count = sum(
            row.kind is ResponseRouteKind.ACTIVE
            and dict(row.route_refs[0].attributes).get("binding") == binding
            for row in self._routes.snapshots()
            if row.route_refs
        )
        if count >= _MAX_PENDING_TURNS_PER_CALL:
            raise VoicePlatformError("VOICE_TURN_BACKPRESSURE")

    async def _handle_native_event(self, native):
        if native.event_kind != "message.query":
            if native.event_kind in {"call.interrupted", "dtmf"}:
                logger.info(
                    "Voice native control received: %s",
                    native.event_kind,
                )
            return
        platform = self._require_connected()
        connection = platform.connection(native.session_binding)
        if (
            native.generation != self._context.identity.generation
            or connection.connection_id != native.connection_id
        ):
            raise VoicePlatformError("STALE_CONNECTION_CALLBACK")
        caller = connection.from_number or ""
        handle = (
            "voice:reply:"
            + hashlib.sha256(
                (
                    self._context.identity.instance_id + ":" + native.event_id
                ).encode(),
            ).hexdigest()
        )
        created = self._routes.snapshot(handle) is None
        if created:
            self._admit_turn(native.session_binding)
            await self._persist_route(
                handle,
                self._route(connection, native.sequence),
            )
        session = "voice:" + native.platform_session_id
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=native.event_id,
            event_kind="message.query",
            conversation={"id": session, "type": "dm", "thread_id": None},
            sender_id=caller,
            acl_sender_id=caller,
            actor_unknown=not bool(caller),
            sender_name="",
            content_parts=({"type": "text", "text": native.payload["text"]},),
            metadata={
                "session_id": session,
                "user_id": caller,
                "debounce_key": native.event_id,
                "is_dm": True,
                "connection_id": native.connection_id,
                "turn_id": str(native.sequence),
            },
            response_handle=handle,
        )
        if await self._admit_event(event, created) is None:
            raise VoicePlatformError("VOICE_HOST_ADMISSION_FAILED")

    async def _open(self, params, request):
        self._identity(params)
        platform = self._require_connected()
        target = decode_reply_target(str(params["to_handle"]))
        session = target["session_id"] if target else str(params["to_handle"])
        call_sid = session.removeprefix("voice:")
        connection = platform._calls.get(call_sid)
        if connection is None:
            raise VoicePlatformError("CALL_CLOSED")
        platform.connection(connection.session_binding)
        self._admit_turn(connection.session_binding)
        handle = "voice:reply:" + uuid.uuid4().hex
        await self._persist_route(
            handle,
            self._route(connection, "api:" + uuid.uuid4().hex),
        )
        return {"response_handle": handle}

    async def _perform_send(self, params):
        if params.operation.value != "message.create":
            raise VoicePlatformError("OUTBOUND_OPERATION_UNSUPPORTED")
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        connection = platform.connection(route["binding"])
        if (
            route["generation"] != str(self._context.identity.generation)
            or route["connection_id"] != connection.connection_id
            or route["call_sid"] != connection.platform_session_id
        ):
            raise VoicePlatformError("CALL_CLOSED")
        completed = params.content_source is ContentSource.EVENT
        if completed:
            text = " ".join(
                p["text"].strip()
                for p in params.content_parts
                if p["type"] == "text" and p["text"]
            )
        else:
            if any(p["type"] != "text" for p in params.content_parts):
                raise VoicePlatformError("OUTBOUND_CONTENT_UNSUPPORTED")
            text = "\n".join(p["text"] for p in params.content_parts)
        if text:
            await platform.send_text(
                route["binding"],
                text,
                completed=completed,
            )
        return ResponseResourceRef.create(
            "voice.delivery",
            params.delivery_id,
            {
                "binding": route["binding"],
                "turn_id": route["turn_id"],
                "final": "true",
            },
        )

    async def _perform_reaction(self, params):
        raise VoicePlatformError("REACTION_UNSUPPORTED")

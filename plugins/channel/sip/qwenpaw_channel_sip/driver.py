# -*- coding: utf-8 -*-
"""SIP transcription and speech through the normal shared response lifecycle."""

from __future__ import annotations

import uuid

from qwenpaw.channel_protocol.models import ContentSource, InboundEvent
from qwenpaw.channel_protocol.response_lifecycle import (
    ResponseResourceRef,
    ResponseCleanupState,
)
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.channel_protocol.targets import decode_reply_target

from .platform import SIPPlatform, SIPPlatformError

_MAX_PENDING_PER_CALL = 32


class SIPDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__("sip", "sip.shared.responses", SIPPlatformError)

    async def start(self, config):
        if self._platform is not None:
            raise RuntimeError("SIP_RESOURCES_ALREADY_OWNED")
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        if not self._config.get("enabled", False):
            await self._state_changed("disconnected")
            return
        self._platform = SIPPlatform()
        await self._state_changed("connecting")
        try:
            await self._platform.start(
                self._config,
                self._transcript,
                self._state_changed,
                self._diagnostic,
            )
        except BaseException:
            await self._state_changed("failed")
            raise

    async def _state_changed(self, state):
        connected = state == "connected" and not self._stopping
        if connected != self._connected:
            self._connection_generation += 1
        self._connected = connected
        await self._context.set_platform_state(state)

    def _require_connected(self):
        if (
            self._stopping
            or not self._connected
            or self._platform is None
            or not self._platform._accepting
        ):
            raise ValueError("NOT_CONNECTED")
        return self._platform

    def response_policy(self, response_handle):
        # Completed messages only; no placeholder or token-level TTS default.
        return ResponsePolicy(
            send_format=SendFormatPolicy(False, False, False, False, True),
            raw_completed_text="text_sources",
        )

    async def _new_route(self, route):
        pending = sum(
            row.cleanup_state is not ResponseCleanupState.COMPLETE
            and any(
                dict(ref.attributes).get("call_id") == route["call_id"]
                and dict(ref.attributes).get("connection_epoch")
                == route["connection_epoch"]
                for ref in row.route_refs
            )
            for row in self._routes.snapshots()
        )
        if pending >= _MAX_PENDING_PER_CALL:
            raise SIPPlatformError("SIP_PENDING_TURNS_CAPACITY")
        handle = "sip:reply:" + uuid.uuid4().hex
        attrs = {**route, "generation": str(self._context.identity.generation)}
        await self._persist_route(handle, attrs)
        return handle

    async def _open(self, params, request):
        self._identity(params)
        platform = self._require_connected()
        decoded = decode_reply_target(params["to_handle"])
        target = (
            (decoded["session_id"] or decoded["user_id"])
            if decoded
            else params["to_handle"]
        )
        call_id = target.removeprefix("sip:")
        route = platform.target(call_id)
        handle = await self._new_route(route)
        return {"response_handle": handle}

    async def _transcript(self, call, route, text):
        self._require_connected().current(route)
        handle = await self._new_route(route)
        caller = call.from_uri or ""
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id="sip:transcript:" + uuid.uuid4().hex,
            event_kind="message.query",
            conversation={
                "id": call.session_id,
                "type": "dm",
                "thread_id": None,
            },
            sender_id=caller,
            acl_sender_id=caller,
            actor_unknown=not bool(caller),
            sender_name="",
            content_parts=({"type": "text", "text": text},),
            response_handle=handle,
            metadata={
                "session_id": call.session_id,
                "user_id": caller,
                "sender_id": caller,
                "is_group": False,
                "debounce_key": "sip:"
                + call.connection_epoch
                + ":"
                + route["turn_id"],
            },
        )
        # Shared admission retains this event identity for any IPC retry.
        await self._admit_event(event, True)

    async def _perform_send(self, params):
        if params.operation.value != "message.create":
            raise SIPPlatformError("SIP_OPERATION_UNSUPPORTED")
        route = self._route_attrs(params.to_handle)
        if route.get("generation") != str(self._context.identity.generation):
            raise SIPPlatformError("CALL_CLOSED")
        self._require_connected().current(route)
        if any(part.get("type") != "text" for part in params.content_parts):
            raise SIPPlatformError("SIP_CONTENT_UNSUPPORTED")
        if params.content_source is ContentSource.EVENT:
            sources = params.raw_completed_text_sources
            if sources is None:
                raise SIPPlatformError("SIP_RAW_COMPLETED_TEXT_UNAVAILABLE")
            if (
                sources.error_source is not None
                or sources.getter_state == "error"
            ):
                raise SIPPlatformError("SIP_COMPLETED_TEXT_EXTRACTION_FAILED")
            text = " ".join(value for value in sources.getter_texts if value)
            if not text:
                text = next(
                    (value for value in sources.top_texts if value),
                    "",
                )
            if not text:
                text = next(
                    (value for value in sources.nested_texts if value),
                    "",
                )
        else:
            text = "\n".join(part["text"] for part in params.content_parts)
        wrote = await self._platform.play(route, text)
        return ResponseResourceRef.create(
            "sip.delivery",
            params.delivery_id,
            {**route, "audio_written": "true" if wrote else "false"},
        )

    async def _perform_reaction(self, params):
        raise SIPPlatformError("REACTION_UNSUPPORTED")

    async def stop(self):
        self._stopping = True
        self._connected = False
        self._connection_generation += 1
        if self._platform is not None:
            await self._platform.close()
            self._platform = None
        await self._context.set_platform_state("disconnected")

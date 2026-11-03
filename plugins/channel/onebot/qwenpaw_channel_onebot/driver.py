# -*- coding: utf-8 -*-
"""OneBot native events and delivery over the standard v2 shared runner."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
from collections.abc import Mapping
import uuid

from qwenpaw.channel_protocol.models import EndpointParams, InboundEvent
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.channel_protocol.targets import decode_reply_target

from .codec import (
    _normalize_segments,
    _reply_message_id,
    _segment_types,
    _with_quoted_context,
    parse_segments,
    session_id,
)
from .platform import OneBotPlatform, OneBotPlatformError


class OneBotDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "onebot",
            "onebot.shared.responses",
            OneBotPlatformError,
        )
        self._self_id = None
        self._admissions = OrderedDict()
        self._endpoint_maybe_registered = False

    async def start(self, config):
        if self._platform is not None:
            raise RuntimeError("ONEBOT_RESOURCES_ALREADY_OWNED")
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        if not config.get("enabled", False):
            await self._state_changed("disconnected")
            return
        platform = self._platform = OneBotPlatform()
        await self._state_changed("connecting")
        try:
            await platform.prepare(
                self._config,
                {"access_token": config.get("access_token", "")},
            )
            await platform.start(
                self._handle_platform_event,
                self._endpoint_changed,
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

    async def _endpoint_changed(self, operation, endpoint):
        if self._stopping:
            raise RuntimeError("ONEBOT_STOPPING")
        await self._state_changed("connecting")
        params = EndpointParams(
            **self._context.identity.to_mapping(),
            protocol="ws",
            host=endpoint.host,
            port=endpoint.port,
            path="/ws",
            public_base_url=None,
            readiness=endpoint.readiness,
            bound_externally=endpoint.bound_externally,
            auth_required=endpoint.auth_required,
        )
        self._endpoint_maybe_registered = True
        try:
            result = await self._context.peer.call(
                "ingress.endpoint." + operation,
                params.to_mapping(),
            )
        except Exception as exc:
            # This specific JSON-RPC error proves there was no handler/effect.
            # It remains a startup failure, never a substitute registration ACK.
            if (
                getattr(exc, "code", None) == -32601
                and operation == "register"
            ):
                self._endpoint_maybe_registered = False
            raise
        expected = "registered" if operation == "register" else "updated"
        if not isinstance(result, Mapping) or (
            result.get("status") != expected
            or result.get("generation") != self._context.identity.generation
            or result.get("readiness") != endpoint.readiness
        ):
            raise ValueError("ONEBOT_ENDPOINT_ACK_INVALID")
        if self._stopping:
            raise RuntimeError("ONEBOT_STOPPING")
        if endpoint.readiness == "ready":
            await self._state_changed("connected")

    def _require_connected(self):
        if (
            self._stopping
            or not self._connected
            or self._platform is None
            or not self._platform._accepting
            or self._platform.listen_port is None
        ):
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        self._stopping = True
        self._connected = False
        self._connection_generation += 1
        failures = []
        if self._platform is not None:
            try:
                await self._platform.close()
            except Exception as exc:
                failures.append(exc)
        if self._endpoint_maybe_registered:
            try:
                result = await self._context.peer.call(
                    "ingress.endpoint.unregister",
                    self._context.identity.to_mapping(),
                )
                if not isinstance(result, Mapping) or (
                    result.get("status") != "unregistered"
                    or result.get("generation")
                    != self._context.identity.generation
                ):
                    raise ValueError("ONEBOT_ENDPOINT_ACK_INVALID")
            except Exception as exc:
                failures.append(exc)
            else:
                self._endpoint_maybe_registered = False
        if failures:
            raise RuntimeError("ONEBOT_STOP_INCOMPLETE") from failures[0]
        self._platform = None
        self._admissions.clear()
        await self._context.set_platform_state("disconnected")

    def response_policy(self, response_handle):
        return ResponsePolicy(
            send_format=SendFormatPolicy(
                False,
                False,
                True,
                False,
                True,
                parts_preserve_order=True,
            ),
        )

    @staticmethod
    def _target(handle, meta):
        decoded = decode_reply_target(str(handle))
        target = (
            decoded["session_id"] or decoded["user_id"]
            if decoded
            else str(handle)
        )
        if target.startswith("onebot:g:"):
            target = "group:" + target[len("onebot:g:") :]
        elif target.startswith("onebot:"):
            native = target[len("onebot:") :].split(":")
            target = "group:" + native[0] if len(native) > 1 else native[0]
        elif decoded:
            target = decoded["user_id"]
        group = bool(meta.get("is_group")) or target.startswith("group:")
        value = (
            meta.get("group_id") or target.removeprefix("group:")
            if group
            else meta.get("sender_id") or target
        )
        try:
            number = str(int(value))
        except (TypeError, ValueError) as exc:
            raise OneBotPlatformError("OUTBOUND_TARGET_UNKNOWN") from exc
        return {"to_handle": "group:" + number if group else number}

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        route = self._target(
            params["to_handle"],
            dict(params.get("meta") or {}),
        )
        handle = "onebot:reply:" + uuid.uuid4().hex
        await self._persist_route(handle, route)
        return {"response_handle": handle}

    async def _handle_platform_event(self, value):
        if self._stopping or not self._connected:
            return
        if value.get("post_type") == "meta_event":
            if (
                value.get("meta_event_type") == "lifecycle"
                and value.get("self_id") is not None
            ):
                self._self_id = str(value["self_id"])
            return
        if value.get("post_type") != "message":
            return
        native_id = value.get("message_id")
        event_id = "onebot:message:" + (
            str(native_id)
            if native_id is not None and str(native_id)
            else uuid.uuid4().hex
        )
        prior = self._admissions.get(event_id)
        if prior is True:
            self._admissions.move_to_end(event_id)
            return
        payload = (
            prior
            if isinstance(prior, dict)
            else await self._normalize_message(value)
        )
        if payload is None:
            return
        self._admissions[event_id] = payload
        self._admissions.move_to_end(event_id)
        while len(self._admissions) > 4096:
            self._admissions.popitem(last=False)
        if await self._message(event_id, payload):
            self._admissions[event_id] = True
            self._admissions.move_to_end(event_id)
            while len(self._admissions) > 4096:
                self._admissions.popitem(last=False)

    async def _normalize_message(self, value):
        platform = self._require_connected()
        user = str(value.get("user_id") or "")
        group = str(value.get("group_id") or "")
        is_group = value.get("message_type") == "group"
        if not user or (is_group and not group):
            return None
        if value.get("self_id") is not None:
            self._self_id = str(value["self_id"])
        segments = _normalize_segments(value.get("message", []))
        parts, mentioned, media = parse_segments(segments, self._self_id)
        reply = _reply_message_id(segments)
        if not parts and reply is None:
            return None
        if (
            is_group
            and self._config.get("require_mention", False)
            and not mentioned
        ):
            return None
        message_type = "group" if is_group else "private"
        if reply is not None:
            quoted_segments = await self._quoted_segments(reply)
            quoted_parts, _, quoted_media = parse_segments(
                quoted_segments,
                self._self_id,
            )
            quoted = await platform._inbound_media.resolve(
                quoted_parts,
                quoted_media,
                message_type,
                {**value, "message": quoted_segments},
            )
            current = await platform._inbound_media.resolve(
                parts,
                media,
                message_type,
                {**value, "message": segments},
            )
            parts = _with_quoted_context(quoted, current)
        else:
            parts = await platform._inbound_media.resolve(
                parts,
                media,
                message_type,
                {**value, "message": segments},
            )
        if not parts:
            return None
        sender = value.get("sender")
        sender = sender if isinstance(sender, Mapping) else {}
        meta = {
            "message_type": message_type,
            "message_id": str(value.get("message_id", "")),
            "sender_id": user,
            "user_name": str(
                sender.get("card") or sender.get("nickname") or user,
            ),
            "group_id": group if is_group else "",
            "is_group": is_group,
            "bot_mentioned": mentioned,
        }
        session = session_id(
            user,
            meta,
            bool(self._config.get("share_session_in_group", False)),
        )
        return {
            "parts": parts,
            "meta": meta,
            "session_id": session,
            "sender_id": user,
        }

    async def _quoted_segments(self, message_id):
        try:
            native_id = int(message_id)
        except ValueError:
            native_id = message_id
        try:
            result = await self._require_connected().call_api(
                "get_msg",
                {"message_id": native_id},
            )
        except OneBotPlatformError:
            return []
        data = result.get("data")
        data = data if isinstance(data, Mapping) else {}
        segments = _normalize_segments(data.get("message"))
        raw = _normalize_segments(data.get("raw_message"))
        return (
            raw
            if raw
            and _segment_types(segments) == ["text"]
            and _segment_types(raw) != ["text"]
            else segments
        )

    async def _message(self, event_id, payload):
        self._require_connected()
        meta = payload["meta"]
        handle = (
            "onebot:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        created = self._routes.snapshot(handle) is None
        if created:
            await self._persist_route(
                handle,
                self._target(payload["sender_id"], meta),
            )
        session = payload["session_id"]
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind="message",
            conversation={
                "id": meta["group_id"]
                if meta["is_group"]
                else payload["sender_id"],
                "type": "group" if meta["is_group"] else "dm",
                "thread_id": None,
            },
            sender_id=payload["sender_id"],
            acl_sender_id=payload["sender_id"],
            sender_name=meta["user_name"],
            content_parts=tuple(payload["parts"]),
            metadata={
                **meta,
                "user_id": payload["sender_id"],
                "session_id": session,
                "debounce_key": session,
            },
            response_handle=handle,
        )
        return await self._admit_event(event, created) is not None

    async def _perform_send(self, params):
        if params.operation.value != "message.create":
            raise OneBotPlatformError("OUTBOUND_OPERATION_UNSUPPORTED")
        receipt = await self._require_connected().send_message(
            self._route_attrs(params.to_handle)["to_handle"],
            params.content_parts,
            params.content_source,
        )
        return ResponseResourceRef.create(
            "onebot.delivery",
            params.delivery_id,
            receipt,
        )

    async def _perform_reaction(self, params):
        raise OneBotPlatformError("REACTION_UNSUPPORTED")

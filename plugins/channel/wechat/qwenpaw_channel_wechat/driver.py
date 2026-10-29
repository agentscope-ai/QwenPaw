# -*- coding: utf-8 -*-
"""WeChat routes and receipts over the existing shared response protocol."""

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
from .errors import WeChatDeliveryError


class WeChatDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "wechat",
            "wechat.shared.responses",
            WeChatDeliveryError,
        )

    @staticmethod
    async def manage(request):
        from .management import manage

        return await manage(request)

    async def start(self, config):
        from .platform import WeChatPlatform

        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        self._platform = WeChatPlatform(
            self._config,
            self._message,
            self._state_changed,
            on_auth_required=self._context.notify_auth_required,
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
        # Accepted public seam, deliberately no private buffering/fallback.
        delay = None
        if self._config.get("message_merge_enabled", False):
            delay = self._config.get("message_merge_delay_ms") or 0
        return ResponsePolicy(
            prepare=True,
            send_format=SendFormatPolicy(True, True, True, False, True),
            text_merge_delay_ms=delay,
            text_merge_flush_before_media=delay is None,
            text_merge_separator_newlines=1 if delay is None else 3,
            text_merge_format_on_flush=delay is not None,
        )

    @staticmethod
    def _target(handle, meta):
        target = decode_reply_target(str(handle))
        session = target["session_id"] if target else str(handle)
        user = target["user_id"] if target else str(handle)
        sender = meta.get("wechat_from_user_id") or (
            session.removeprefix("wechat:group:")
            if session.startswith("wechat:group:")
            else (
                session.removeprefix("wechat:")
                if session.startswith("wechat:")
                else user
            )
        )
        if not str(sender).strip():
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        return {
            "wechat_from_user_id": str(sender),
            "wechat_context_token": str(
                meta.get("wechat_context_token") or "",
            ),
            "session_id": str(meta.get("session_id") or session),
            "user_id": str(meta.get("user_id", user)),
        }

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        handle = "wechat:reply:" + uuid.uuid4().hex
        await self._persist_route(
            handle,
            self._target(params["to_handle"], params.get("meta") or {}),
        )
        return {"response_handle": handle}

    async def _message(self, value):
        platform = self._require_connected()
        event_id = value["event_id"]
        handle = (
            "wechat:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        meta, session = dict(value["meta"]), value["session_id"]
        route = self._target(
            session,
            {**meta, "session_id": session, "user_id": value["user_id"]},
        )
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if created or snapshot.kind.value != "terminal":
            await self._persist_route(handle, route)
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind="message",
            conversation={
                "id": meta["wechat_group_id"] or value["sender_id"],
                "type": "group" if meta["is_group"] else "dm",
                "thread_id": None,
            },
            sender_id=value["sender_id"],
            acl_sender_id=value["acl_sender_id"],
            sender_name=value["sender_id"],
            content_parts=tuple(value["content_parts"]),
            metadata={
                **meta,
                "session_id": session,
                "user_id": value["user_id"],
                "debounce_key": session,
            },
            response_handle=handle,
        )
        if created or snapshot.kind.value != "terminal":
            platform.start_typing(
                handle,
                route["wechat_from_user_id"],
                route["wechat_context_token"],
            )
        return await self._admit_event(event, created) is not None

    async def _perform_prepare(self, params):
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        platform.start_typing(
            params.to_handle,
            route["wechat_from_user_id"],
            route["wechat_context_token"]
            or platform.context_token(route["wechat_from_user_id"]),
        )

    async def _perform_send(self, params):
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        if (
            params.operation.value != "message.create"
            or params.approval is not None
            or params.approval_resolution is not None
        ):
            raise WeChatDeliveryError("OPERATION_UNSUPPORTED")
        if any(
            ref.kind == "wechat.context_invalid"
            for ref in self._routes.snapshot(params.to_handle).resource_refs
        ):
            raise WeChatDeliveryError("CONTEXT_TOKEN_INVALID")
        try:
            await platform.send_parts(route, params.content_parts)
        except WeChatDeliveryError as exc:
            if exc.reason_code == "CONTEXT_TOKEN_INVALID":
                self._routes.record_delivery(
                    params.to_handle,
                    [
                        ResponseResourceRef.create(
                            "wechat.context_invalid",
                            params.to_handle,
                            {},
                        ),
                    ],
                )
                await self._checkpoint()
            raise

    async def _before_cleanup_complete(self, snapshot):
        if self._platform is not None:
            await self._platform.finish_response(snapshot.response_handle)
        return snapshot

# -*- coding: utf-8 -*-
"""Generic Mattermost Driver with authenticated connection and scoped typing."""

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
from .platform import MattermostDeliveryError, MattermostPlatform


class MattermostDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "mattermost",
            "mattermost.shared.responses",
            MattermostDeliveryError,
        )

    async def start(self, config):
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        for snapshot in self._routes.pending_cleanups():
            async with self._lock(snapshot.response_handle):
                await self._cleanup(snapshot)
        self._platform = MattermostPlatform(
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

    def _require_connected(self):
        if not self._connected or self._stopping or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        await self._stop_platform()

    def response_policy(self, response_handle):
        return ResponsePolicy(
            prepare=self._config.get("show_typing") is not False,
            send_format=SendFormatPolicy(False, False),
        )

    def _target(self, handle, meta):
        if meta.get("mm_channel_id"):
            return str(meta["mm_channel_id"]), str(meta.get("root_id") or "")
        target = decode_reply_target(str(handle))
        session = target["session_id"] if target is not None else str(handle)
        if session.startswith("mattermost_dm:"):
            return session.split(":", 1)[-1], str(meta.get("root_id") or "")
        # The legacy thread target has no persistent root -> channel mapping.
        return (target["user_id"] if target is not None else str(handle)), str(
            meta.get("root_id") or "",
        )

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        target, root = self._target(
            params["to_handle"],
            params.get("meta") or {},
        )
        if not target:
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        handle = "mattermost:reply:" + uuid.uuid4().hex
        await self._persist_route(
            handle,
            {"mm_channel_id": target, "root_id": root},
        )
        return {"response_handle": handle}

    async def _message(self, value):
        event_id = value["post_id"]
        handle = (
            "mattermost:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if snapshot is None or snapshot.kind.value != "terminal":
            await self._persist_route(
                handle,
                {"mm_channel_id": value["channel"], "root_id": value["root"]},
            )
        sender = value["sender"]
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind="message",
            conversation={
                "id": value["channel"],
                "type": "dm" if value["channel_type"] == "D" else "group",
                "thread_id": value["root"] or None,
            },
            sender_id=sender,
            acl_sender_id=sender,
            sender_name="",
            content_parts=tuple(value["parts"]),
            metadata={
                "session_id": value["session"],
                "user_id": sender,
                "debounce_key": value["session"],
                "mm_channel_id": value["channel"],
                "root_id": value["root"],
                "channel_type": value["channel_type"],
                "post_id": event_id,
                "bot_mentioned": value["mentioned"],
            },
            response_handle=handle,
        )
        return await self._admit_event(event, created) is not None

    async def _perform_send(self, params):
        platform = self._require_connected()
        if params.operation.value != "message.create":
            raise MattermostDeliveryError("OPERATION_UNSUPPORTED")
        attrs = self._route_attrs(params.to_handle)
        resource = await platform.send_parts(
            attrs["mm_channel_id"],
            attrs["root_id"],
            params.content_parts,
        )
        return ResponseResourceRef.create(
            "mattermost.delivery",
            params.delivery_id,
            resource,
        )

    async def _perform_prepare(self, params):
        platform = self._require_connected()
        if self._config.get("show_typing") is False:
            return None
        attrs = self._route_attrs(params.to_handle)
        await platform.start_typing(
            params.to_handle,
            attrs["mm_channel_id"],
            attrs["root_id"],
        )
        return ResponseResourceRef.create(
            "mattermost.delivery",
            params.delivery_id,
            {"typing": "true"},
        )

    async def _release_local_response(self, handle):
        if self._platform is not None:
            await self._platform.stop_typing(handle)

    async def _before_cleanup_complete(self, snapshot):
        if self._platform is not None:
            await self._platform.stop_typing(snapshot.response_handle)
        return snapshot

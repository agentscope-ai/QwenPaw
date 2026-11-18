# -*- coding: utf-8 -*-
"""Synthetic platform with real host queues and response journal."""

import json
import os
from pathlib import Path
import time
import uuid

from qwenpaw.utils.media_paths import local_media_path
from qwenpaw.channel_protocol.models import InboundEvent
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.response_policy import ResponsePolicy
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)


LEDGER = globals().get("LEDGER", "")
VERSION = globals().get("VERSION", "")


class DeliveryError(Exception):
    reason_code = "SAMPLE_SEND_FAILED"
    retryable = False
    side_effect_possible = False


def record(kind, **values):
    with Path(LEDGER).open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "kind": kind,
                    "pid": os.getpid(),
                    "version": VERSION,
                    "time": time.monotonic_ns(),
                    **values,
                },
            )
            + "\n",
        )


class Driver(SharedResponseDriver):
    def __init__(self):
        super().__init__("sample", "sample.responses", DeliveryError)

    def bind(self, context):
        super().bind(context)
        context.peer.register_method("sample.identity", self.identity)
        context.peer.register_method("sample.emit", self.emit)

    async def start(self, config):
        if globals().get("FAIL_START"):
            record("start_failed")
            raise RuntimeError("sample startup failure")
        self._config = dict(config)
        self._connected, self._platform = True, self
        self._connection_generation += 1
        await self._restore_responses()
        record("connected", config=config)
        await self._context.set_platform_state("connected")

    async def stop(self):
        self._stopping = True
        await self._checkpoint()
        self._connected = False
        record("stopped")

    def _require_connected(self):
        if not self._connected:
            raise ValueError("NOT_CONNECTED")
        return self

    async def identity(self, _params, _request):
        sdk = None
        if self._config.get("use_sdk"):
            import sample_shared_sdk

            sdk = sample_shared_sdk.VALUE
        return {
            "pid": os.getpid(),
            "version": VERSION,
            "source": __file__,
            "config": self._config,
            "sdk": sdk,
            "identity": self._context.identity.to_mapping(),
        }

    def response_policy(self, response_handle):
        return ResponsePolicy.from_mapping(
            {
                "streaming": True,
                "prepare": False,
                "completion_reaction": False,
            },
        )

    async def _open(self, params, _request):
        self._identity(params)
        from qwenpaw.channel_protocol.targets import decode_reply_target

        target = decode_reply_target(params["to_handle"])
        room = target["session_id"] if target else params["to_handle"]
        handle = "sample:reply:" + uuid.uuid4().hex
        await self._persist_route(handle, {"room": room})
        return {"response_handle": handle}

    async def emit(self, params, _request):
        handle = "sample:reply:" + uuid.uuid4().hex
        room, sender = params.get("room", "room"), params.get(
            "sender",
            "alice",
        )
        await self._persist_route(handle, {"room": room})
        event = InboundEvent.from_mapping(
            {
                **self._context.identity.to_mapping(),
                "event_id": params["id"],
                "event_kind": "message",
                "conversation": {"id": room, "type": "dm"},
                "sender_id": sender,
                "acl_sender_id": sender,
                "sender_name": sender,
                "content_parts": [
                    {"type": "text", "text": params.get("text", "hello")},
                ],
                "metadata": {
                    "session_id": room,
                    "user_id": sender,
                    "debounce_key": room,
                },
                "response_handle": handle,
            },
        )
        return await self._context.peer.call(
            "event.batch",
            {
                "batch_id": params["id"],
                "events": [event.to_mapping()],
            },
        )

    async def _perform_send(self, params):
        record(
            "sent",
            room=self._route_attrs(params.to_handle)["room"],
            operation=params.operation.value,
            content_parts=list(params.content_parts),
            text=params.accumulated_text,
            approval=params.approval.to_mapping() if params.approval else None,
            files=[
                Path(local_media_path(p["file_url"])).read_bytes().hex()
                for p in params.content_parts
                if p.get("type") == "file"
            ],
        )
        return ResponseResourceRef.create(
            "sample.delivery",
            params.delivery_id,
        )

    async def _before_cleanup_complete(self, snapshot):
        record("finished", outcome=snapshot.outcome.value)
        return snapshot

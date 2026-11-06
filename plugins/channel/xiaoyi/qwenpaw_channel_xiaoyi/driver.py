# -*- coding: utf-8 -*-
"""XiaoYi native routes and effects over the common shared worker contract."""

from __future__ import annotations

from dataclasses import replace
import asyncio
import hashlib
import time
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

from .errors import XiaoYiDeliveryError
from .platform import XiaoYiPlatform
from .constants import WORKING_FRAME_INTERVAL, WORKING_FRAME_MAX_WAIT


class XiaoYiDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "xiaoyi",
            "xiaoyi.shared.responses",
            XiaoYiDeliveryError,
        )
        self._working_tasks: dict[str, asyncio.Task] = {}

    async def start(self, config):
        if self._platform is not None:
            raise RuntimeError("XIAOYI_RESOURCES_ALREADY_OWNED")
        self._config = dict(config)
        self._stopping = False
        await self._restore_responses()
        if not self._config.get("enabled", False):
            await self._state_changed("disconnected")
            return
        self._platform = XiaoYiPlatform(
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
        connected = state == "connected" and not self._stopping
        if connected != self._connected:
            self._connection_generation += 1
        self._connected = connected
        await self._context.set_platform_state(state)
        if connected and self._platform is not None:
            self._platform._spawn(self._resume_cleanups())

    async def _resume_cleanups(self):
        for pending in self._routes.pending_cleanups():
            try:
                async with self._lock(pending.response_handle):
                    current = self._routes.snapshot(pending.response_handle)
                    if (
                        current.cleanup_state
                        is not ResponseCleanupState.COMPLETE
                    ):
                        await self._cleanup(current)
            except Exception:
                await self._diagnostic("XIAOYI_RESPONSE_CLEANUP_PENDING")

    def _require_connected(self):
        if (
            self._stopping
            or not self._connected
            or self._platform is None
            or not self._platform.connected
        ):
            raise ValueError("NOT_CONNECTED")
        return self._platform

    async def stop(self):
        for task in self._working_tasks.values():
            task.cancel()
        self._working_tasks.clear()
        await self._stop_platform()

    def response_policy(self, response_handle):
        # The legacy XiaoYi path sends completed events as append artifacts;
        # it did not opt into the host's token streaming hooks.
        return ResponsePolicy(
            send_format=SendFormatPolicy(False, False, True, False, True),
            continue_on_delivery_error=True,
        )

    def response_open_policy(self):
        return ResponsePolicy(continue_on_delivery_error=True)

    async def _open(self, params, request):
        self._identity(params)
        platform = self._require_connected()
        meta = dict(params.get("meta") or {})
        target = decode_reply_target(str(params["to_handle"]))
        if target:
            session = target["session_id"]
            if not session.startswith("xiaoyi:"):
                session = target["user_id"]
        else:
            session = str(params["to_handle"])
        with self.target_resolution():
            route = platform.resolve_target(session, meta)
        handle = "xiaoyi:reply:" + uuid.uuid4().hex
        await self._persist_route(handle, route)
        return {"response_handle": handle}

    async def _message(self, value):
        self._require_connected()
        event_id = value["event_id"]
        handle = (
            "xiaoyi:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if created:
            await self._persist_route(handle, value["route"])
        # An existing route always retains its first task/message/server.
        native_session = value["session_id"]
        session = "xiaoyi:" + native_session
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind="message",
            conversation={
                "id": native_session,
                "type": "dm",
                "thread_id": None,
            },
            sender_id=native_session,
            acl_sender_id=native_session,
            sender_name="",
            content_parts=tuple(value["content_parts"]),
            metadata={
                **value["meta"],
                "user_id": native_session,
                "session_id": session,
                "debounce_key": session,
            },
            response_handle=handle,
        )
        return await self._admit_event(event, created) is not None

    async def _perform_send(self, params):
        if params.operation.value != "message.create":
            raise XiaoYiDeliveryError("OPERATION_UNSUPPORTED")
        route = self._route_attrs(params.to_handle)
        receipt = await self._require_connected().send_parts(
            route,
            params.content_parts,
            params.content_source,
        )
        self._resume_working_frames(params.to_handle, route)
        return ResponseResourceRef.create(
            "xiaoyi.delivery",
            params.delivery_id,
            receipt,
        )

    def _working_frame_interval(self):
        try:
            interval = float(
                self._config.get("working_frame_interval", WORKING_FRAME_INTERVAL),
            )
        except (TypeError, ValueError):
            interval = WORKING_FRAME_INTERVAL
        if interval <= 0:
            return 0.0
        return min(interval, float(WORKING_FRAME_MAX_WAIT))

    def _resume_working_frames(self, handle, route):
        """Restart the client-refresh loop for one response route.

        Every outbound send means the turn is alive and the client is
        waiting; between sends and before the first artifact the app shows
        nothing at all (issue #8394). The loop stops itself after
        WORKING_FRAME_MAX_WAIT so an abandoned session cannot tick forever.
        """
        interval = self._working_frame_interval()
        if interval <= 0:
            return
        previous = self._working_tasks.pop(handle, None)
        if previous is not None:
            previous.cancel()

        async def loop():
            deadline = time.monotonic() + WORKING_FRAME_MAX_WAIT
            platform = self._platform
            while (
                platform is not None
                and self._working_tasks.get(handle) is asyncio.current_task()
                and time.monotonic() < deadline
            ):
                await platform.send_working(route)
                await asyncio.sleep(interval)

        task = self._platform._spawn(loop())
        self._working_tasks[handle] = task

    def _cancel_working_frames(self, handle):
        task = self._working_tasks.pop(handle, None)
        if task is not None:
            task.cancel()

    async def _perform_reaction(self, params):
        raise XiaoYiDeliveryError("REACTION_UNSUPPORTED")

    async def _record_finish(self, snapshot, step, attributes):
        ref = ResponseResourceRef.create("xiaoyi.finish", step, attributes)
        updated = replace(
            snapshot,
            version=snapshot.version + 1,
            resource_refs=tuple(
                sorted(
                    [
                        old
                        for old in snapshot.resource_refs
                        if (old.kind, old.resource_id)
                        != (ref.kind, ref.resource_id)
                    ]
                    + [ref],
                ),
            ),
        )
        self._routes.restore(updated)
        await self._checkpoint()
        return updated

    async def _before_cleanup_complete(self, snapshot):
        self._cancel_working_frames(snapshot.response_handle)
        route = dict(snapshot.route_refs[0].attributes)
        if not route.get("session_id") or not route.get("task_id"):
            return snapshot
        for step in ("completed", "final"):
            prior = next(
                (
                    ref
                    for ref in snapshot.resource_refs
                    if ref.kind == "xiaoyi.finish" and ref.resource_id == step
                ),
                None,
            )
            if prior is not None:
                state = dict(prior.attributes)["state"]
                if state == "acknowledged":
                    continue
                if state == "unknown":
                    raise RuntimeError("XIAOYI_FINISH_RESULT_UNKNOWN")
            platform = self._require_connected()
            attributes = {
                **route,
                "state": "unknown",
                "reason_code": "PLATFORM_RESULT_UNKNOWN",
            }
            snapshot = await self._record_finish(snapshot, step, attributes)
            try:
                await platform.send_finish_step(route, step)
            except XiaoYiDeliveryError as exc:
                attributes.update(
                    state="unknown" if exc.side_effect_possible else "failed",
                    reason_code=exc.reason_code,
                )
                await self._record_finish(snapshot, step, attributes)
                raise
            attributes.update(state="acknowledged", reason_code="")
            snapshot = await self._record_finish(snapshot, step, attributes)
        return snapshot

    def _compact_receipt(self, snapshot):
        compact = super()._compact_receipt(snapshot)
        # Retain independent completion receipts through the normal shared TTL.
        return replace(
            compact,
            resource_refs=tuple(
                sorted(
                    compact.resource_refs
                    + tuple(
                        ref
                        for ref in snapshot.resource_refs
                        if ref.kind == "xiaoyi.finish"
                    ),
                ),
            ),
        )

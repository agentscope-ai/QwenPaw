# -*- coding: utf-8 -*-
"""XiaoYi native routes and effects over the common shared worker contract."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import logging
import uuid

from qwenpaw.channel_protocol.models import (
    InboundEvent,
    OutboundOperation,
    ResponseOutcome,
    StreamType,
)
from qwenpaw.channel_protocol.outbound_budget import remaining_send_timeout
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

from .codec import new_artifact_id
from .constants import (
    TEXT_CHUNK_LIMIT,
    WORKING_INTERVAL,
    WORKING_MAX_SECONDS,
    WORKING_SEND_TIMEOUT,
)
from .errors import XiaoYiDeliveryError
from .platform import XiaoYiPlatform

logger = logging.getLogger(__name__)
_STREAM_PART_KINDS = {f"message": f"text", f"reasoning": f"reasoningText"}


class XiaoYiDriver(SharedResponseDriver):
    def __init__(self):
        super().__init__(
            "xiaoyi",
            "xiaoyi.shared.responses",
            XiaoYiDeliveryError,
        )
        self._working: dict[str, asyncio.Task] = {}

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
        try:
            await self._platform.start()
        except Exception:
            if not self._stopping:
                await self._state_changed(f"failed")
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
        try:
            await self._stop_platform()
        finally:
            self._working.clear()

    def response_policy(self, response_handle):
        route = self._route_attrs(response_handle)
        native_task = bool(route.get(f"task_id"))
        return ResponsePolicy(
            prepare=native_task,
            streaming=native_task
            and self._config.get(f"streaming_enabled") is True,
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

    async def _perform_prepare(self, params):
        handle = params.to_handle
        route = self._route_attrs(handle)
        if handle in self._working or not route.get(f"task_id"):
            return None
        platform = self._platform
        remaining = remaining_send_timeout()
        timeout = WORKING_SEND_TIMEOUT
        if remaining is not None:
            timeout = min(timeout, remaining / 2)
        await self._send_working(platform, route, timeout)
        if not self._stopping:
            self._working[handle] = platform._spawn(
                self._refresh_working(handle, platform, route),
            )
        return None

    @staticmethod
    async def _send_working(platform, route, timeout):
        if timeout <= 0:
            return
        try:
            async with asyncio.timeout(timeout):
                await platform.send_status(route, f"working", f"Working...")
        except (XiaoYiDeliveryError, TimeoutError):
            logger.debug(f"xiaoyi: working status could not be delivered")

    async def _refresh_working(self, handle, platform, route):
        try:
            async with asyncio.timeout(WORKING_MAX_SECONDS):
                while True:
                    await asyncio.sleep(WORKING_INTERVAL)
                    await self._send_working(
                        platform,
                        route,
                        WORKING_SEND_TIMEOUT,
                    )
        except TimeoutError:
            pass
        finally:
            if self._working.get(handle) is asyncio.current_task():
                self._working.pop(handle)

    async def _release_local_response(self, handle):
        task = self._working.pop(handle, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _cleanup(self, snapshot):
        await self._release_local_response(snapshot.response_handle)
        await super()._cleanup(snapshot)

    async def _perform_send(self, params):
        platform = self._require_connected()
        route = self._route_attrs(params.to_handle)
        operation = params.operation
        if operation is OutboundOperation.MESSAGE_CREATE:
            streaming = self.response_policy(params.to_handle).streaming
            receipt = await platform.send_parts(
                route,
                params.content_parts,
                params.content_source,
                replace_event_text=streaming,
                media_final=route.get(f"origin") != f"inbound",
            )
        elif operation is OutboundOperation.STREAM_START:
            if not self.response_policy(params.to_handle).streaming:
                raise XiaoYiDeliveryError(f"STREAM_DISABLED")
            receipt = {
                **route,
                f"stream_type": params.stream_type.value,
                f"sequence": f"0",
                f"final": f"false",
            }
        elif operation in (
            OutboundOperation.STREAM_DELTA,
            OutboundOperation.STREAM_END,
        ):
            return await self._update_stream(platform, params)
        else:
            raise XiaoYiDeliveryError("OPERATION_UNSUPPORTED")
        return ResponseResourceRef.create(
            "xiaoyi.delivery",
            params.delivery_id,
            receipt,
        )

    async def _update_stream(self, platform, params):
        handle = params.to_handle
        ref = self._delivery_resource(handle, params.target_delivery_id)
        resource = dict(ref.attributes) if ref else {}
        if resource.get(f"stream_type") != params.stream_type.value:
            raise XiaoYiDeliveryError(f"OUTBOUND_TARGET_UNKNOWN")
        if resource.get(f"unsettled") == f"true":
            raise XiaoYiDeliveryError(
                f"PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        if (
            params.sequence <= int(resource[f"sequence"])
            or resource[f"final"] == f"true"
        ):
            raise XiaoYiDeliveryError(f"STREAM_SEQUENCE_STALE")
        final = params.operation is OutboundOperation.STREAM_END
        if final or params.stream_type is StreamType.MESSAGE:
            await self._write_stream(platform, params, ref, resource, final)
        resource.update(
            sequence=str(params.sequence),
            final=str(final).lower(),
        )
        return ResponseResourceRef.create(ref.kind, ref.resource_id, resource)

    async def _write_stream(self, platform, params, ref, resource, final):
        handle = params.to_handle
        text = params.accumulated_text
        if not text:
            return
        if params.stream_type is StreamType.REASONING:
            text = f"{text}\n\n"
        digest = hashlib.sha256(text.encode()).hexdigest()
        if not final and digest == resource.get(f"snapshot_sha256"):
            return

        resource.update(
            artifact_id=new_artifact_id(),
            unsettled=f"true",
        )
        intent = ResponseResourceRef.create(
            ref.kind,
            ref.resource_id,
            resource,
        )
        self._routes.record_delivery(handle, [intent])
        try:
            await self._checkpoint()
        except ValueError as exc:
            self._routes.record_delivery(handle, [ref])
            if str(exc) == f"RESPONSE_STATE_CAPACITY":
                raise XiaoYiDeliveryError(f"RESPONSE_STATE_CAPACITY") from exc
            raise

        wrote_chunk = False
        kind = _STREAM_PART_KINDS[resource[f"stream_type"]]
        try:
            for start in range(0, len(text), TEXT_CHUNK_LIMIT):
                chunk = text[start : start + TEXT_CHUNK_LIMIT]
                await platform.send_stream_part(
                    resource,
                    resource[f"artifact_id"],
                    kind,
                    chunk,
                    append=start > 0,
                    last_chunk=start + len(chunk) == len(text),
                )
                wrote_chunk = True
        except XiaoYiDeliveryError as exc:
            if not exc.side_effect_possible:
                if wrote_chunk:
                    raise XiaoYiDeliveryError(
                        f"PARTIAL_DELIVERY",
                        side_effect_possible=True,
                    ) from exc
                self._routes.record_delivery(handle, [ref])
            raise
        resource.pop(f"unsettled")
        resource.pop(f"artifact_id")
        resource[f"snapshot_sha256"] = digest

    def _needs_stream_cleanup(self, ref):
        # Unsettled snapshots fence task finalization in shared cleanup.
        return dict(ref.attributes).get(f"unsettled") == f"true"

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
        route = dict(snapshot.route_refs[0].attributes)
        if not route.get("session_id") or not route.get("task_id"):
            return snapshot
        outcome = snapshot.outcome
        state = (
            f"canceled"
            if outcome is ResponseOutcome.CANCELLED
            else outcome.value
        )
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
                prior_state = dict(prior.attributes)[f"state"]
                if prior_state == f"acknowledged":
                    continue
                if prior_state == f"unknown":
                    raise RuntimeError("XIAOYI_FINISH_RESULT_UNKNOWN")
            platform = self._require_connected()
            attributes = {
                **route,
                "state": "unknown",
                "reason_code": "PLATFORM_RESULT_UNKNOWN",
            }
            snapshot = await self._record_finish(snapshot, step, attributes)
            try:
                await platform.send_finish_step(route, step, state)
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

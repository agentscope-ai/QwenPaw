# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,too-many-return-statements
"""SDK-free durable reply lifecycle shared by platform Drivers."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import uuid

from qwenpaw.channel_protocol.errors import (
    RPC_LIFECYCLE_ERROR,
    RPC_RESPONSE_OPEN_FAILED,
    RpcError,
    RpcTimeoutError,
)
from qwenpaw.channel_protocol.models import (
    send_source_capability,
    RAW_COMPLETED_TEXT_CAPABILITY,
    UNKNOWN_ACTOR_CAPABILITY,
    APPROVAL_RESOLUTION_CAPABILITY,
    EventBatchAck,
    EventBatchParams,
    HostStateParams,
    IdentityParams,
    OutboundResult,
    DeliveryState,
    ResponseFinishResult,
    ResponsePrepareOperation,
)
from qwenpaw.channel_protocol.response_receipts import receipt_key
from qwenpaw.channel_protocol.outbound_budget import (
    DEFAULT_SEND_TIMEOUT,
    await_send,
    send_budget,
)
from qwenpaw.channel_protocol.response_policy import ResponsePolicy
from qwenpaw.channel_protocol.reliability import RetryPolicy, events_for_retry
from qwenpaw.channel_protocol.response_lifecycle import (
    ResponseCleanupState,
    ResponseResourceRef,
    ResponseRouteAggregate,
    ResponseRouteSnapshot,
    ResponseStateError,
)

_MAX_ROUTES = 128
_STREAM_RECEIPTS = 4
_CHECKPOINT_BYTES = 768 * 1024


class SharedResponseDriver:
    """Journal platform intent before effects and retain unknown receipts."""

    def __init__(
        self,
        kind,
        state_key,
        delivery_error,
        *,
        extra_rpc_pressure_reasons=(),
    ):
        self._kind = kind
        self._state_key = state_key
        self.delivery_error = delivery_error
        self._context = None
        self._platform = None
        self._config = {}
        self._routes = ResponseRouteAggregate(max_entries=_MAX_ROUTES)
        self._locks = {}
        self._checkpoint_lock = asyncio.Lock()
        self._inflight_admissions = {}
        self._connected = False
        self._stopping = False
        self._connection_generation = 0
        self._rpc_pressure_reasons = frozenset(
            (
                "INGRESS_BACKPRESSURE",
                "RPC_BACKPRESSURE",
                *extra_rpc_pressure_reasons,
            ),
        )
        self._core_batch_backpressure_total = 0
        self._core_batch_timeout_total = 0
        self._core_batch_retry_total = 0

    async def _stop_platform(self):
        self._stopping = True
        self._connected = False
        self._connection_generation += 1
        if self._platform is not None:
            await self._platform.stop()
            self._platform = None
        await self._context.set_platform_state("disconnected")

    def _check_connection(self, generation):
        if self._stopping or generation != self._connection_generation:
            raise RuntimeError("STALE_CONNECTION_CALLBACK")

    def diagnostics(self) -> dict[str, int]:
        """Return a detached snapshot of this Driver's Core admission counts."""
        return {
            "core_batch_backpressure_total": (
                self._core_batch_backpressure_total
            ),
            "core_batch_timeout_total": self._core_batch_timeout_total,
            "core_batch_retry_total": self._core_batch_retry_total,
        }

    async def _restore_responses(self):
        rows = (await self._state("get", self._state_key))["value"] or []
        if not isinstance(rows, list) or len(rows) > _MAX_ROUTES:
            raise ValueError("RESPONSE_STATE_INVALID")
        migrated = False
        for row in rows:
            snapshot = ResponseRouteSnapshot.from_mapping(row)
            compact = self._compact_stream_attempts(snapshot)
            if compact != snapshot:
                snapshot = replace(compact, version=snapshot.version + 1)
                migrated = True
            if await self._archived(snapshot.response_handle):
                migrated = True
                continue
            if snapshot.cleanup_state is ResponseCleanupState.COMPLETE:
                compact = self._compact_receipt(snapshot)
                if compact != snapshot:
                    snapshot = replace(compact, version=snapshot.version + 1)
                if not self._evictable(snapshot):
                    await self._receipt(
                        "put",
                        snapshot.response_handle,
                        snapshot,
                    )
                    migrated = True
                    continue
            self._routes.restore(snapshot)
        if migrated:
            await self._checkpoint()

    async def _persist_route(self, handle, attrs):
        # Serialize opening against archive publication and removal. A stale
        # open must not race a durable closed-handle fence.
        async with self._checkpoint_lock:
            if await self._archived(handle):
                raise ResponseStateError(
                    "RESPONSE_CLOSED",
                    "response route is closed",
                )
            rows = self._routes.snapshots()
            if len(rows) >= _MAX_ROUTES:
                completed = sorted(
                    (row for row in rows if self._evictable(row)),
                    key=lambda row: row.closed_at_ms,
                )
                if completed:
                    self._evict(completed[0].response_handle)
            for old in self._routes.expired_completed():
                if self._evictable(old):
                    self._routes.commit_gc(old)
            snapshot, created = self._routes.open(
                handle,
                [
                    ResponseResourceRef.create(
                        self._kind + ".route",
                        handle,
                        attrs,
                    ),
                ],
            )
            try:
                await self._write_checkpoint()
            except BaseException:
                if created:
                    self._routes.rollback_open(handle, snapshot.version)
                raise
        return handle

    async def _receipt(self, operation, handle, snapshot=None):
        return await self._context.peer.call(
            "host.receipt." + operation,
            HostStateParams(
                **self._context.identity.to_mapping(),
                key=receipt_key(self._state_key, handle),
                value=snapshot.to_mapping() if snapshot is not None else None,
            ).to_mapping(),
        )

    async def _archived(self, handle):
        value = (await self._receipt("get", handle))["value"]
        return ResponseRouteSnapshot.from_mapping(value) if value else None

    async def _archive(self, candidate):
        async with self._checkpoint_lock:
            # Durable evidence must precede removal from both live budgets.
            try:
                await self._receipt(
                    "put",
                    candidate.response_handle,
                    candidate,
                )
            except Exception:
                # A lost RPC acknowledgement can still mean a committed put.
                if (
                    await self._archived(candidate.response_handle)
                    != candidate
                ):
                    raise
            self._evict(candidate.response_handle)
            await self._write_checkpoint()

    async def _retire_archived(self, handle):
        await self._release_local_response(handle)
        async with self._checkpoint_lock:
            if self._routes.snapshot(handle) is not None:
                self._evict(handle)
                await self._write_checkpoint()

    async def _release_local_response(self, handle):
        """Release local resources without repeating native effects."""

    def bind(self, context):
        self._context = context
        for name, handler in (
            ("channel.send", self._send),
            ("channel.reaction", self._reaction),
            ("channel.response.open", self._open),
            ("channel.response.prepare", self._prepare),
            ("channel.response.finish", self._finish),
            ("channel.response.describe", self._describe),
        ):
            context.peer.register_method(
                name,
                (
                    handler
                    if name == "channel.response.describe"
                    else self._outbound_handler(handler)
                ),
            )

    def _outbound_handler(self, handler):
        async def execute(params, request):
            with send_budget(
                getattr(self._context, "send_timeout", DEFAULT_SEND_TIMEOUT),
            ):
                return await handler(params, request)

        execute._channel_effect_budget = True
        return execute

    def response_policy(self, response_handle: str) -> ResponsePolicy:
        """Read route policy; subclasses may narrow optional operations."""
        return ResponsePolicy()

    def response_open_policy(self) -> ResponsePolicy:
        """Default to strict delivery before any response route exists."""
        return ResponsePolicy()

    @contextmanager
    def target_resolution(self):
        """Classify only a determinate target refusal, before route allocation."""
        try:
            yield
        except self.delivery_error as exc:
            if exc.side_effect_possible is not False:
                raise
            policy = self.response_open_policy()
            if not isinstance(policy, ResponsePolicy):
                raise ValueError("SCHEMA_MISMATCH") from exc
            result = OutboundResult.from_mapping(
                {
                    "delivery_id": "unroutable",
                    "state": "failed",
                    "reason_code": exc.reason_code,
                    "retryable": exc.retryable,
                },
            )
            if not result.reason_code:
                raise ValueError("SCHEMA_MISMATCH") from exc
            raise RpcError(
                RPC_RESPONSE_OPEN_FAILED,
                "response target unavailable",
                data={
                    "operation": "channel.response.open",
                    "result": result.to_mapping(),
                    "continue_on_delivery_error": policy.continue_on_delivery_error,
                },
            ) from exc

    async def _describe(self, params, request):
        self._identity(params)
        if (
            not isinstance(params, dict)
            or set(params)
            != {*self._context.identity.to_mapping(), "response_handle"}
            or not isinstance(params["response_handle"], str)
        ):
            raise ValueError("SCHEMA_MISMATCH")
        self._require_connected()
        handle = params["response_handle"]
        if await self._archived(handle):
            raise ResponseStateError(
                "RESPONSE_CLOSED",
                "response route is closed",
            )
        async with self._lock(handle):
            self._route_attrs(handle)
            policy = self.response_policy(handle)
            if not isinstance(policy, ResponsePolicy):
                raise ValueError("SCHEMA_MISMATCH")
            return policy.to_mapping()

    def _identity(self, value):
        identity = self._context.identity
        if isinstance(value, dict):
            value = IdentityParams.from_mapping(
                {key: value[key] for key in identity.to_mapping()},
            )
        if any(
            getattr(value, key) != getattr(identity, key)
            for key in identity.to_mapping()
        ):
            raise RpcError(
                RPC_LIFECYCLE_ERROR,
                "stale channel generation",
                data={"reason_code": "STALE_GENERATION", "retryable": False},
            )
        return identity

    async def _state(self, operation, key, value=None):
        return await self._context.peer.call(
            "host.state." + operation,
            HostStateParams(
                **self._context.identity.to_mapping(),
                key=key,
                value=value,
            ).to_mapping(),
        )

    async def _diagnostic(self, reason):
        await self._context.peer.notify(
            "channel.diagnostic",
            {
                **self._context.identity.to_mapping(),
                "reason_code": reason,
            },
        )

    async def _checkpoint(
        self,
        candidate=None,
        *,
        reserve_bytes=0,
        admission=None,
    ):
        async with self._checkpoint_lock:
            await self._write_checkpoint(
                candidate,
                reserve_bytes=reserve_bytes,
                admission=admission,
            )

    @staticmethod
    def _json_bytes(value):
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def _compact_stream_attempts(self, snapshot):
        resources = {
            ref.resource_id: ref
            for ref in snapshot.resource_refs
            if ref.kind == self._kind + ".delivery"
        }
        removable = set()
        for target, resource in tuple(resources.items()):
            attrs = dict(resource.attributes)
            if (
                attrs.get("unsettled") == "true"
                or attrs.get("cleanup") == "unknown"
            ):
                continue
            confirmed = int(attrs.get("sequence", "0"))
            receipts = sorted(
                (
                    (int(dict(ref.attributes).get("sequence", "0")), ref)
                    for ref in snapshot.resource_refs
                    if ref.kind == self._kind + ".attempt"
                    and dict(ref.attributes).get("operation") == "stream.delta"
                    and dict(ref.attributes).get("state") == "acknowledged"
                    and dict(ref.attributes).get("target_delivery_id")
                    == target
                    and int(dict(ref.attributes).get("sequence", "0"))
                    <= confirmed
                ),
                reverse=True,
            )
            old = receipts[_STREAM_RECEIPTS:]
            if old:
                removable.update(ref for _, ref in old)
                attrs["compacted_sequence"] = str(
                    max(
                        int(attrs.get("compacted_sequence", "0")),
                        max(sequence for sequence, _ in old),
                    ),
                )
                resources[target] = ResponseResourceRef.create(
                    resource.kind,
                    target,
                    attrs,
                )
        if not removable:
            return snapshot
        return replace(
            snapshot,
            resource_refs=tuple(
                sorted(
                    (
                        resources.get(ref.resource_id, ref)
                        if ref.kind == self._kind + ".delivery"
                        else ref
                    )
                    for ref in snapshot.resource_refs
                    if ref not in removable
                ),
            ),
        )

    def _checkpoint_reserve(self, snapshots):
        reserve = 0
        for snapshot in snapshots:
            if snapshot.cleanup_state is ResponseCleanupState.COMPLETE:
                continue
            mapping = snapshot.to_mapping()
            terminal = dict(
                mapping,
                kind="terminal",
                outcome="completed",
                cleanup_state="complete",
                closed_at_ms=2**63 - 1,
                cleanup_completed_at_ms=2**63 - 1,
                expires_at_ms=2**63 - 1,
            )
            reserve += max(
                256 if snapshot.cleanup_state is None else 0,
                self._json_bytes(terminal) - self._json_bytes(mapping),
            )
            attempts = [
                dict(ref.attributes)
                for ref in snapshot.resource_refs
                if ref.kind == self._kind + ".attempt"
            ]
            streams = {
                ref.resource_id: dict(ref.attributes)
                for ref in snapshot.resource_refs
                if ref.kind == self._kind + ".delivery"
                and dict(ref.attributes).get("stream_type")
                and dict(ref.attributes).get("final") != "true"
            }
            for ref in snapshot.resource_refs:
                attrs = dict(ref.attributes)
                if (
                    ref.kind == self._kind + ".attempt"
                    and attrs.get("operation") == "stream.start"
                    and attrs.get("state") != "failed"
                    and not any(
                        resource.kind == self._kind + ".delivery"
                        and resource.resource_id == ref.resource_id
                        for resource in snapshot.resource_refs
                    )
                ):
                    attrs = {
                        "sequence": "0",
                        "stream_type": "reasoning",
                        "final": "false",
                    }
                    streams[ref.resource_id] = attrs
                    reserve += self._json_bytes(
                        ResponseResourceRef.create(
                            self._kind + ".delivery",
                            ref.resource_id,
                            attrs,
                        ).to_mapping(),
                    )
            for target, attrs in streams.items():
                ending = snapshot.cleanup_state is not None or any(
                    row.get("operation") == "stream.end"
                    and row.get("target_delivery_id") == target
                    and row.get("state") == "unknown"
                    for row in attempts
                )
                intent = ResponseResourceRef.create(
                    self._kind + ".attempt",
                    "0" * 32,
                    {
                        "fingerprint": "0" * 64,
                        "operation": "stream.end",
                        "state": "unknown",
                        "reason_code": "PLATFORM_RESULT_UNKNOWN",
                        "target_delivery_id": target,
                        "sequence": str(int(attrs.get("sequence", "0")) + 1),
                    },
                )
                cleanup = dict(
                    attrs,
                    final="true",
                    cleanup="unknown",
                    sequence=str(int(attrs.get("sequence", "0")) + 1),
                )
                growth = max(
                    0,
                    self._json_bytes(cleanup) - self._json_bytes(attrs),
                )
                reserve += (
                    max(256, growth)
                    if ending
                    else max(
                        1024,
                        self._json_bytes(intent.to_mapping()) + growth,
                    )
                )
                for admission in self._inflight_admissions.values():
                    if (
                        admission.to_handle == snapshot.response_handle
                        and getattr(admission, "target_delivery_id", None)
                        == target
                        and getattr(admission, "accumulated_text", None)
                        is not None
                        and "text" in attrs
                    ):
                        reserve += max(
                            0,
                            self._json_bytes(admission.accumulated_text)
                            - self._json_bytes(attrs["text"]),
                        )
        return reserve

    async def _write_checkpoint(
        self,
        candidate=None,
        *,
        reserve_bytes=0,
        admission=None,
    ):
        originals = {
            row.response_handle: row for row in self._routes.snapshots()
        }
        snapshots = {
            handle: (
                replace(compact, version=row.version + 1)
                if compact != row
                else row
            )
            for handle, row in originals.items()
            for compact in (self._compact_stream_attempts(row),)
        }
        if candidate is not None:
            snapshots[candidate.response_handle] = candidate
        if admission is not None:
            # Other responses must see this growth while native I/O awaits.
            self._inflight_admissions[
                admission.to_handle,
                admission.delivery_id,
            ] = admission
        while (
            self._json_bytes([row.to_mapping() for row in snapshots.values()])
            + self._checkpoint_reserve(snapshots.values())
            + reserve_bytes
            > _CHECKPOINT_BYTES
        ):
            completed = sorted(
                (
                    row
                    for row in self._routes.snapshots()
                    if self._evictable(row)
                    and (
                        candidate is None
                        or row.response_handle != candidate.response_handle
                    )
                ),
                key=lambda row: row.closed_at_ms,
            )
            if not completed:
                raise ValueError("RESPONSE_STATE_CAPACITY")
            self._evict(completed[0].response_handle)
            snapshots.pop(completed[0].response_handle, None)
        await self._state(
            "put",
            self._state_key,
            [row.to_mapping() for row in snapshots.values()],
        )
        for handle, row in snapshots.items():
            if row != originals.get(handle) and self._routes.snapshot(
                handle,
            ) == originals.get(handle):
                if candidate is None or handle != candidate.response_handle:
                    self._routes.restore(row)

    def _lock(self, handle):
        if handle not in self._locks:
            if len(self._locks) >= _MAX_ROUTES:
                for key in tuple(self._locks):
                    if (
                        self._routes.snapshot(key) is None
                        and not self._locks[key].locked()
                    ):
                        self._locks.pop(key)
            if len(self._locks) >= _MAX_ROUTES:
                raise ValueError("RESPONSE_CAPACITY")
            self._locks[handle] = asyncio.Lock()
        return self._locks[handle]

    async def _admit_event(self, event, created):
        if getattr(
            event,
            "actor_unknown",
            False,
        ) and UNKNOWN_ACTOR_CAPABILITY not in getattr(
            self._context,
            "capabilities",
            (),
        ):
            raise RpcError(-32602, "Unknown actor capability was not declared")
        generation = self._connection_generation
        policy = RetryPolicy(initial_delay=0.1, max_delay=1.0, max_attempts=5)
        batch = EventBatchParams(uuid.uuid4().hex, (event,))
        uncertain = False
        for attempt in range(1, policy.max_attempts + 1):
            self._check_connection(generation)
            ack = None
            try:
                ack = EventBatchAck.from_mapping(
                    await self._context.peer.call(
                        "event.batch",
                        batch.to_mapping(),
                    ),
                )
                if ack.batch_id not in {None, batch.batch_id}:
                    raise ValueError("HOST_ACK_IDENTITY_MISMATCH")
                self._core_batch_backpressure_total += sum(
                    row.reason_code == "INGRESS_BACKPRESSURE"
                    for row in ack.rejected_events
                )
            except Exception as exc:
                if isinstance(exc, RpcTimeoutError):
                    self._core_batch_timeout_total += 1
                elif (
                    isinstance(exc, RpcError)
                    and isinstance(exc.data, dict)
                    and isinstance(exc.data.get("reason_code"), str)
                    and exc.data["reason_code"] in self._rpc_pressure_reasons
                ):
                    self._core_batch_backpressure_total += 1
                uncertain = True
                ack = None
            self._check_connection(generation)
            if ack and event.event_id in (
                *ack.accepted_event_ids,
                *ack.duplicate_event_ids,
            ):
                if (
                    created
                    and not uncertain
                    and event.event_id in ack.duplicate_event_ids
                ):
                    from qwenpaw.channel_protocol.models import ResponseOutcome

                    async with self._lock(event.response_handle):
                        snapshot = self._routes.begin_finish(
                            event.response_handle,
                            ResponseOutcome.CANCELLED,
                        )
                        await self._checkpoint()
                        await self._cleanup(snapshot)
                return ack, uncertain
            retries, delay = events_for_retry(
                batch,
                ack,
                attempt=attempt,
                policy=policy,
            )
            if not retries:
                rejected = (
                    next(
                        (
                            row
                            for row in ack.rejected_events
                            if row.event_id == event.event_id
                        ),
                        None,
                    )
                    if ack
                    else None
                )
                exhausted = not rejected or rejected.retryable
                if exhausted:
                    await self._diagnostic("HOST_ADMISSION_EXHAUSTED")
                if created and not uncertain:
                    from qwenpaw.channel_protocol.models import ResponseOutcome

                    async with self._lock(event.response_handle):
                        snapshot = self._routes.begin_finish(
                            event.response_handle,
                            ResponseOutcome.CANCELLED,
                        )
                        await self._checkpoint()
                        await self._cleanup(snapshot)
                        if self._evictable(
                            self._routes.snapshot(event.response_handle),
                        ):
                            self._evict(event.response_handle)
                            await self._checkpoint()
                if not exhausted:
                    return None
                raise RuntimeError("HOST_ADMISSION_EXHAUSTED")
            if delay is not None:
                self._core_batch_retry_total += 1
            await asyncio.sleep(delay)
        raise RuntimeError("HOST_ADMISSION_EXHAUSTED")

    def _result(self, delivery_id, state, reason=None, retryable=False):
        return OutboundResult(
            delivery_id,
            DeliveryState(state),
            reason,
            retryable,
        ).to_mapping()

    async def _send(self, params, request):
        self._identity(params)
        source_capability = send_source_capability(
            params.content_source,
            getattr(self._context, "capabilities", ()),
        )
        for field, capability in (
            (params.content_source, source_capability),
            (params.approval_resolution, APPROVAL_RESOLUTION_CAPABILITY),
            (params.raw_completed_text_sources, RAW_COMPLETED_TEXT_CAPABILITY),
        ):
            if field is not None and capability not in (
                getattr(self._context, "capabilities", ())
            ):
                raise RpcError(-32602, "Send capability was not declared")
        handle = params.to_handle
        archived = await self._archived(handle)
        if archived:
            return self._replay(params, archived)
        async with self._lock(handle):
            return await self._delivery(params, self._perform_send)

    async def _prepare(self, params, request):
        self._identity(params)
        if (
            set(params)
            != {
                *self._context.identity.to_mapping(),
                "response_handle",
                "delivery_id",
            }
            or not isinstance(params["response_handle"], str)
            or not params["response_handle"]
            or not isinstance(params["delivery_id"], str)
            or params["delivery_id"]
            != hashlib.sha256(
                (params["response_handle"] + ":prepare").encode(),
            ).hexdigest()
        ):
            raise ValueError("SCHEMA_MISMATCH")
        operation = ResponsePrepareOperation(
            **self._context.identity.to_mapping(),
            delivery_id=params["delivery_id"],
            to_handle=params["response_handle"],
        )
        archived = await self._archived(operation.to_handle)
        if archived:
            return self._replay(operation, archived)
        async with self._lock(operation.to_handle):
            return await self._delivery(operation, self._perform_prepare)

    async def _perform_prepare(self, params):
        raise self.delivery_error(
            "PREPARE_UNSUPPORTED",
            side_effect_possible=False,
        )

    @staticmethod
    def _operation_fingerprint(params):
        return hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in params.to_mapping().items()
                    if key != "generation"
                },
                sort_keys=True,
            ).encode(),
        ).hexdigest()

    def _replay(self, params, snapshot):
        delivery_id = params.delivery_id
        fingerprint = self._operation_fingerprint(params)
        previous = next(
            (
                ref
                for ref in snapshot.resource_refs
                if ref.kind == self._kind + ".attempt"
                and ref.resource_id == delivery_id
            ),
            None,
        )
        if previous:
            attrs = dict(previous.attributes)
            if attrs["fingerprint"] != fingerprint:
                return self._result(
                    delivery_id,
                    "failed",
                    "DELIVERY_CONFLICT",
                )
            return self._result(
                delivery_id,
                attrs["state"],
                attrs.get("reason_code") or None,
            )
        if snapshot.cleanup_state is ResponseCleanupState.COMPLETE:
            return self._result(delivery_id, "failed", "RESPONSE_CLOSED")
        target = getattr(params, "target_delivery_id", None)
        sequence = getattr(params, "sequence", None)
        if (
            target
            and sequence is not None
            and any(
                ref.kind == self._kind + ".delivery"
                and ref.resource_id == target
                and sequence
                <= int(dict(ref.attributes).get("compacted_sequence", "0"))
                for ref in snapshot.resource_refs
            )
        ):
            return self._result(delivery_id, "failed", "STREAM_SEQUENCE_STALE")
        return None

    async def _delivery(self, params, perform):
        try:
            return await self._delivery_attempt(params, perform)
        finally:
            self._inflight_admissions.pop(
                (params.to_handle, params.delivery_id),
                None,
            )

    async def _delivery_attempt(self, params, perform):
        delivery_id, handle = params.delivery_id, params.to_handle
        try:
            snapshot = self._routes.snapshot(handle)
            if snapshot is None:
                snapshot = await self._archived(handle)
            if snapshot is None:
                return self._result(
                    delivery_id,
                    "failed",
                    "RESPONSE_HANDLE_UNKNOWN",
                )
            replay = self._replay(params, snapshot)
            if replay is not None:
                return replay
            fingerprint = self._operation_fingerprint(params)
            self._require_connected()
            self._routes.admit_operation(handle)
            intent = {
                "fingerprint": fingerprint,
                "operation": getattr(
                    getattr(params, "operation", None),
                    "value",
                    "reaction",
                ),
                "state": "unknown",
                "reason_code": "PLATFORM_RESULT_UNKNOWN",
                "target_delivery_id": getattr(
                    params,
                    "target_delivery_id",
                    None,
                )
                or "",
                "sequence": str(getattr(params, "sequence", None) or 0),
            }
            self._routes.record_delivery(
                handle,
                [
                    ResponseResourceRef.create(
                        self._kind + ".attempt",
                        delivery_id,
                        intent,
                    ),
                ],
            )
            try:
                await self._checkpoint(
                    reserve_bytes=(
                        0
                        if intent["operation"].startswith("stream.")
                        else 1024
                    ),
                    admission=params,
                )
            except ValueError as exc:
                if str(exc) == "RESPONSE_STATE_CAPACITY":
                    current = self._routes.snapshot(handle)
                    self._routes.restore(
                        replace(snapshot, version=current.version + 1),
                    )
                    return self._result(
                        delivery_id,
                        "failed",
                        "RESPONSE_STATE_CAPACITY",
                    )
                raise
        except ResponseStateError as exc:
            return self._result(delivery_id, "failed", exc.reason_code)
        except ValueError:
            return self._result(
                delivery_id,
                "failed",
                (
                    "NOT_CONNECTED"
                    if not self._connected
                    else "LOCAL_ADMISSION_FAILED"
                ),
            )
        result = None
        try:
            with send_budget(
                getattr(self._context, "send_timeout", DEFAULT_SEND_TIMEOUT),
            ):
                resource = await await_send(perform(params))
            if resource:
                self._routes.record_delivery(handle, [resource])
            result = self._result(delivery_id, "acknowledged")
        except self.delivery_error as exc:
            result = self._result(
                delivery_id,
                "unknown" if exc.side_effect_possible else "failed",
                exc.reason_code,
                exc.retryable,
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._checkpoint())
            raise
        except Exception:
            result = self._result(
                delivery_id,
                "unknown",
                "PLATFORM_RESULT_UNKNOWN",
            )
        intent.update(
            state=result["state"],
            reason_code=result.get("reason_code", ""),
        )
        self._routes.record_delivery(
            handle,
            [
                ResponseResourceRef.create(
                    self._kind + ".attempt",
                    delivery_id,
                    intent,
                ),
            ],
        )
        try:
            await self._checkpoint()
        except Exception:
            return self._result(
                delivery_id,
                "unknown",
                "CHECKPOINT_RESULT_UNKNOWN",
            )
        return result

    def _route_attrs(self, handle):
        return dict(self._routes.active_route_refs(handle)[0].attributes)

    def _delivery_resource(self, handle, delivery_id):
        return next(
            (
                ref
                for ref in self._routes.snapshot(handle).resource_refs
                if ref.kind == self._kind + ".delivery"
                and ref.resource_id == delivery_id
            ),
            None,
        )

    async def _reaction(self, params, request):
        self._identity(params)
        archived = await self._archived(params.to_handle)
        if archived:
            return self._replay(params, archived)
        async with self._lock(params.to_handle):
            return await self._delivery(params, self._perform_reaction)

    async def _finish(self, params, request):
        self._identity(params)
        archived = await self._archived(params.response_handle)
        if archived:
            if archived.outcome is not params.outcome:
                raise ResponseStateError(
                    "RESPONSE_OUTCOME_CONFLICT",
                    "response outcome conflicts",
                )
            await self._retire_archived(params.response_handle)
            return ResponseFinishResult(
                params.response_handle,
                params.outcome,
            ).to_mapping()
        async with self._lock(params.response_handle):
            archived = await self._archived(params.response_handle)
            if archived:
                if archived.outcome is not params.outcome:
                    raise ResponseStateError(
                        "RESPONSE_OUTCOME_CONFLICT",
                        "response outcome conflicts",
                    )
                await self._retire_archived(params.response_handle)
                return ResponseFinishResult(
                    params.response_handle,
                    params.outcome,
                ).to_mapping()
            snapshot = self._routes.begin_finish(
                params.response_handle,
                params.outcome,
            )
            await self._checkpoint()
            try:
                await self._cleanup(snapshot)
            except Exception as exc:
                await self._diagnostic("RESPONSE_FINISH_FAILED")
                raise RpcError(
                    RPC_LIFECYCLE_ERROR,
                    "response finish handler failed",
                    data={
                        "reason_code": "RESPONSE_FINISH_FAILED",
                        "retryable": True,
                    },
                ) from exc
        return ResponseFinishResult(
            params.response_handle,
            params.outcome,
        ).to_mapping()

    async def _cleanup(self, snapshot):
        with send_budget(
            getattr(self._context, "send_timeout", DEFAULT_SEND_TIMEOUT),
        ):
            return await self._cleanup_effects(snapshot)

    async def _cleanup_effects(self, snapshot):
        archived = await self._archived(snapshot.response_handle)
        if archived:
            await self._retire_archived(snapshot.response_handle)
            return
        if snapshot.cleanup_state is ResponseCleanupState.COMPLETE:
            if not self._evictable(snapshot):
                await self._archive(self._compact_receipt(snapshot))
            return
        unknown_cleanup = False
        for ref in snapshot.resource_refs:
            resource = dict(ref.attributes)
            if (
                ref.kind != self._kind + ".delivery"
                or not self._needs_stream_cleanup(ref)
                or resource.get("final") == "true"
            ):
                continue
            unknown_end = any(
                attempt.kind == self._kind + ".attempt"
                and dict(attempt.attributes).get("target_delivery_id")
                == ref.resource_id
                and dict(attempt.attributes).get("operation") == "stream.end"
                and dict(attempt.attributes).get("state") == "unknown"
                for attempt in snapshot.resource_refs
            )
            if (
                unknown_end
                or resource.get("unsettled") == "true"
                or resource.get("cleanup") == "unknown"
            ):
                unknown_cleanup = True
                continue
            sequences = [int(resource.get("sequence", "0"))]
            sequences.extend(
                int(dict(attempt.attributes).get("sequence", "0"))
                for attempt in snapshot.resource_refs
                if attempt.kind == self._kind + ".attempt"
                and dict(attempt.attributes).get("target_delivery_id")
                == ref.resource_id
            )
            sequence = max(sequences) + 1
            resource.update(sequence=str(sequence), cleanup="unknown")
            snapshot = self._record_cleanup(
                snapshot,
                ref.resource_id,
                resource,
            )
            await self._checkpoint()
            try:
                await await_send(
                    self._perform_stream_cleanup(ref, resource, sequence),
                )
            except self.delivery_error as exc:
                if not exc.side_effect_possible:
                    resource["cleanup"] = "failed"
                    snapshot = self._record_cleanup(
                        snapshot,
                        ref.resource_id,
                        resource,
                    )
                    await self._checkpoint()
                    raise
                unknown_cleanup = True
                continue
            except Exception:
                # The durable intent fences a cleanup whose result was lost.
                unknown_cleanup = True
                continue
            resource.update(final="true", cleanup="complete")
            snapshot = self._record_cleanup(
                snapshot,
                ref.resource_id,
                resource,
            )
            await self._checkpoint()
        if not unknown_cleanup:
            snapshot = await await_send(
                self._before_cleanup_complete(snapshot),
            )
        candidate = self._routes.cleanup_candidate(
            snapshot.response_handle,
            snapshot.outcome,
        )
        candidate = self._compact_receipt(candidate)
        if not self._evictable(candidate):
            await self._archive(candidate)
            await self._retire_archived(candidate.response_handle)
        else:
            await self._checkpoint(candidate)
            self._routes.commit_cleanup(candidate)

    def _needs_stream_cleanup(self, ref):
        return False

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        raise NotImplementedError

    async def _before_cleanup_complete(self, snapshot):
        return snapshot

    def _record_cleanup(self, snapshot, delivery_id, resource):
        updated = replace(
            snapshot,
            version=snapshot.version + 1,
            resource_refs=tuple(
                sorted(
                    (
                        ResponseResourceRef.create(
                            self._kind + ".delivery",
                            delivery_id,
                            resource,
                        )
                        if ref.kind == self._kind + ".delivery"
                        and ref.resource_id == delivery_id
                        else ref
                    )
                    for ref in snapshot.resource_refs
                ),
            ),
        )
        self._routes.restore(updated)
        return updated

    def _compact_receipt(self, snapshot):
        unknown = tuple(
            ref
            for ref in snapshot.resource_refs
            if ref.kind == self._kind + ".attempt"
            and dict(ref.attributes).get("state") == "unknown"
        )
        unsettled = tuple(
            ref
            for ref in snapshot.resource_refs
            if ref.kind == self._kind + ".delivery"
            and (
                dict(ref.attributes).get("unsettled") == "true"
                or dict(ref.attributes).get("cleanup") == "unknown"
                or any(
                    dict(attempt.attributes).get("target_delivery_id")
                    == ref.resource_id
                    for attempt in unknown
                )
            )
        )
        evidence = (*unknown, *unsettled)
        if unsettled:
            # COMPLETE means local retirement; native uncertainty is preserved.
            evidence += snapshot.route_refs
            evidence += tuple(
                ref
                for ref in snapshot.resource_refs
                if ref.kind
                in {self._kind + ".route", self._kind + ".local_retirement"}
            )
            evidence += (
                ResponseResourceRef.create(
                    self._kind + ".local_retirement",
                    snapshot.response_handle,
                    {"cleanup": "local_only"},
                ),
            )
            for ref in unsettled:
                attrs = dict(ref.attributes)
                if attrs.get("cleanup") != "unknown":
                    continue
                digest = hashlib.sha256(
                    json.dumps(
                        [snapshot.response_handle, ref.to_mapping()],
                        sort_keys=True,
                    ).encode(),
                ).hexdigest()
                evidence += (
                    ResponseResourceRef.create(
                        self._kind + ".attempt",
                        "cleanup:" + digest,
                        {
                            "fingerprint": digest,
                            "operation": "stream.cleanup",
                            "state": "unknown",
                            "reason_code": "STREAM_CLEANUP_UNKNOWN",
                            "target_delivery_id": ref.resource_id,
                            "sequence": attrs.get("sequence", "0"),
                        },
                    ),
                )
        return replace(
            snapshot,
            route_refs=(),
            resource_refs=tuple(sorted(set(evidence))),
            expires_at_ms=(2**63 - 1)
            if evidence
            else snapshot.expires_at_ms,
        )

    def _evictable(self, snapshot):
        return (
            snapshot.cleanup_state is ResponseCleanupState.COMPLETE
            and not any(
                ref.kind == self._kind + ".attempt"
                and dict(ref.attributes).get("state") == "unknown"
                for ref in snapshot.resource_refs
            )
        )

    def _evict(self, handle):
        replacement = ResponseRouteAggregate(max_entries=_MAX_ROUTES)
        for row in self._routes.snapshots():
            if row.response_handle != handle:
                replacement.restore(row)
        self._routes = replacement
        lock = self._locks.get(handle)
        if lock is not None and not lock.locked():
            self._locks.pop(handle, None)

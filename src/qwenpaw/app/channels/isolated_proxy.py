# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""SDK-free BaseChannel adapter for an explicitly owned channel process."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

from qwenpaw.channel_protocol.errors import (
    RPC_LIFECYCLE_ERROR,
    RPC_RESPONSE_OPEN_FAILED,
    RpcError,
    ProtocolValidationError,
)
from qwenpaw.channel_protocol.host import (
    SharedEndpointAuthority,
    SharedEndpointService,
)
from qwenpaw.channel_protocol.rpc import JSONRPC_INTERNAL_ERROR
from qwenpaw.channel_protocol.normalization import normalize_inbound_event
from qwenpaw.channel_protocol.completed_text import project_completed_text
from qwenpaw.channel_protocol.targets import encode_reply_target
from qwenpaw.channel_protocol.response_policy import (
    ResponsePolicy,
    SendFormatPolicy,
)
from qwenpaw.channel_protocol.models import (
    CONTENT_SOURCE_CAPABILITY,
    SEMANTIC_PARTS_CAPABILITY,
    RAW_COMPLETED_TEXT_CAPABILITY,
    UNKNOWN_ACTOR_CAPABILITY,
    APPROVAL_RESOLUTION_CAPABILITY,
    TEXT_MERGE_CAPABILITY,
    AUTH_QRCODE_CAPABILITY,
    AuthRequiredParams,
    ApprovalCardParams,
    ApprovalResolutionParams,
    validate_content_part,
    DeliveryState,
    EventBatchAck,
    EventBatchParams,
    HostStateParams,
    IdentityParams,
    OutboundResult,
    RejectedEvent,
)
from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
from qwenpaw.schemas import Message, AgentRequest
from qwenpaw.utils.io_utils import (
    get_path_lock,
    run_async_to_completion,
    run_sync_io,
)
from qwenpaw.utils.outbound_media import update_outbound_media
from .base import BaseChannel
from .process_supervisor import ChannelCallUnknown, ChannelProcess, LaunchSpec
from .renderer import ChannelDisplayConfig

logger = logging.getLogger(__name__)

_STATE_MAX_BYTES = 1024 * 1024
_STATE_MAX_KEYS = 64
_TEXT_MERGE_MAX_RESPONSES = 128
_TEXT_MERGE_MAX_BYTES = 768 * 1024


def _rpc_result_unknown(error):
    if not isinstance(error.data, dict):
        return False
    return (error.code, error.data.get("reason_code")) in {
        (RPC_LIFECYCLE_ERROR, "PLATFORM_RESULT_UNKNOWN"),
        (JSONRPC_INTERNAL_ERROR, "REQUEST_CANCELLED"),
    }


def _approval_card_params(metadata):
    """Adapt host severity values to the validated approval wire contract."""
    severity = metadata.get("severity", "medium")
    if isinstance(severity, str):
        severity = severity.lower()
        if severity in {"info", "safe"}:
            severity = "medium"
    return ApprovalCardParams.from_mapping(
        {
            "request_id": metadata["approval_request_id"],
            "tool_name": metadata.get("tool_name", "tool"),
            "severity": severity,
        },
    ).to_mapping()


@dataclass
class _ResponseText:
    """One response's unacknowledged host text and owned asynchronous work."""

    to_handle: str
    meta: dict
    identity: dict
    fields: dict | None = None
    raw_text: str | None = None
    size: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    timer: asyncio.Task | None = None
    flush: asyncio.Task | None = None
    error: BaseException | None = None
    closed: bool = False


class ChannelDeliveryError(RuntimeError):
    """Expose a safe, determinate or uncertain platform operation result."""

    def __init__(self, result):
        self.state = result.state.value
        self.reason_code = result.reason_code or "PLATFORM_SEND_FAILED"
        self.side_effect_possible = self.state in {"unknown", "timeout"}
        super().__init__(self.reason_code)


class _ChannelLifecycleError(ChannelDeliveryError):
    """A host lifecycle fence, never a recoverable platform delivery error."""


class _ResponseOpenDeliveryError(RpcError):
    """A closed, determinate refusal from this response.open RPC only."""

    def __init__(self, error):
        data = error.data
        if (
            not isinstance(data, dict)
            or set(data)
            != {"operation", "result", "continue_on_delivery_error"}
            or data["operation"] != "channel.response.open"
            or type(data["continue_on_delivery_error"]) is not bool
            or not isinstance(data["result"], dict)
            or set(data["result"])
            != {
                "delivery_id",
                "state",
                "reason_code",
                "retryable",
            }
        ):
            raise ProtocolValidationError("Invalid response open failure")
        result = OutboundResult.from_mapping(data["result"])
        if (
            result.state is not DeliveryState.FAILED
            or result.delivery_id != "unroutable"
            or not result.reason_code
        ):
            raise ProtocolValidationError(
                "Invalid response open failure result",
            )
        self.result = result
        self.continue_on_delivery_error = data["continue_on_delivery_error"]
        super().__init__(error.code, error.message, data=data)


class IsolatedChannelProxy(BaseChannel):
    """Keep queue, policy and Agent execution in the parent process."""

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        service = getattr(self, "endpoint_service", None)
        if not self._enabled and service is not None:
            service.fence()

    @property
    def _ingress_open(self):
        return self._endpoint_ingress_open

    @_ingress_open.setter
    def _ingress_open(self, value):
        self._endpoint_ingress_open = bool(value)
        service = getattr(self, "endpoint_service", None)
        if not self._endpoint_ingress_open and service is not None:
            service.pause()

    def _normalize_event(self, event):
        payload = normalize_inbound_event(event)
        payload["content_parts"] = Message(
            content=payload["content_parts"],
        ).content
        return payload

    def __init__(
        self,
        process,
        *,
        launch_spec: LaunchSpec,
        descriptor: SharedChannelDescriptor,
        channel_process: ChannelProcess | None = None,
        workspace_dir: Path | None = None,
        on_reply_sent=None,
        display_config=None,
        connection_timeout: float | None = None,
    ):
        if connection_timeout is not None and (
            type(connection_timeout) not in (int, float)
            or not math.isfinite(connection_timeout)
            or connection_timeout <= 0
        ):
            raise ValueError("Connection timeout must be finite and positive")
        self._connection_timeout = connection_timeout
        if descriptor.channel_key != launch_spec.channel_key:
            raise ValueError("IDENTITY_MISMATCH")
        self.channel = descriptor.channel_key
        self.descriptor = descriptor
        config = dict(launch_spec.config)
        self.enabled = bool(
            launch_spec.enabled and config.get("enabled", True),
        )
        self.bot_prefix = str(config.get("bot_prefix") or "")
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            display_config=display_config
            or ChannelDisplayConfig(
                **{
                    key: config[key]
                    for key in ChannelDisplayConfig.__dataclass_fields__
                    if key in config
                },
            ),
            **{
                key: config[key]
                for key in (
                    "dm_policy",
                    "group_policy",
                    "allow_from",
                    "deny_message",
                    "require_mention",
                    "no_text_debounce",
                    "streaming_enabled",
                    "access_control_dm",
                    "access_control_group",
                )
                if key in config
            },
        )
        self._workspace_dir = (
            Path(workspace_dir).expanduser().resolve()
            if workspace_dir
            else None
        )
        if self._workspace_dir:
            config.setdefault("workspace_dir", str(self._workspace_dir))
            config.setdefault("media_dir", str(self._workspace_dir / "media"))
        self._launch_spec = replace(
            launch_spec,
            config=config,
            enabled=self.enabled,
        )
        self.channel_process = channel_process or ChannelProcess()
        self._accepted = OrderedDict()
        self._admission_denials = OrderedDict()
        self._enqueue_async = None
        self._ingress_open = True
        self.last_stop_result = None
        self._owner_registry = None
        self._admission_wakeup = None
        self._state = {}
        state_path = self._state_path()
        self._state_lock = (
            get_path_lock(state_path)
            if state_path is not None
            else asyncio.Lock()
        )
        self._state_closed = False
        self._ingress_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._started = False
        self._response_context = ContextVar(
            f"channel_response_{id(self)}",
            default=None,
        )
        self._buffered_handles = {}
        self._text_merge = {}
        self._text_merge_bytes = 0
        self._text_merge_stopping = False
        self._last_diagnostic = None
        self.endpoint_service = SharedEndpointService(
            authority=SharedEndpointAuthority(
                channel_key=self.channel,
                instance_id=self._launch_spec.instance_id,
                source_revision=self._launch_spec.source_revision,
                capabilities=self.descriptor.capabilities,
                process=self.channel_process,
                enabled=lambda: self.enabled,
                ingress_open=lambda: self._ingress_open,
            ),
            plugin_id=self._launch_spec.plugin_id,
            workspace_id=self._launch_spec.workspace_id,
        )
        self.endpoint_service.register_rpc_methods(self.channel_process)
        self.channel_process.register_notification(
            "channel.diagnostic",
            self._diagnostic,
        )
        self.channel_process.register_notification(
            "channel.auth.required",
            self._auth_required,
        )
        self.channel_process.register_method("event.batch", self._event_batch)
        for operation in ("get", "put", "delete"):

            async def handle(params, request, operation=operation):
                return await self._host_state(operation, params)

            self.channel_process.register_method(
                "host.state." + operation,
                handle,
            )

        for operation in ("get", "put"):

            async def receipt(params, request, operation=operation):
                return await self._host_receipt(operation, params)

            self.channel_process.register_method(
                "host.receipt." + operation,
                receipt,
            )

    @classmethod
    def from_config(
        cls,
        process,
        config,
        on_reply_sent=None,
        display_config=None,
        no_text_debounce=True,
        *,
        launch_spec: LaunchSpec | None = None,
        descriptor: SharedChannelDescriptor | None = None,
        channel_process=None,
        workspace_dir=None,
    ):
        if launch_spec is None or descriptor is None:
            raise ValueError("CHANNEL_PREPARATION_REQUIRED")
        values = (
            config.model_dump()
            if hasattr(config, "model_dump")
            else dict(config)
        )
        values["no_text_debounce"] = no_text_debounce
        return cls(
            process,
            launch_spec=replace(launch_spec, config=values),
            descriptor=descriptor,
            channel_process=channel_process,
            workspace_dir=workspace_dir,
            on_reply_sent=on_reply_sent,
            display_config=display_config,
        )

    def _identity(self):
        snapshot = self.channel_process.health_snapshot()
        return IdentityParams(
            self.channel,
            self._launch_spec.instance_id,
            snapshot["generation"] or self._launch_spec.generation,
        )

    def bind_dependency_usage(self, usage, lease):
        """Publish standard audit evidence to an already-bound exact lease."""
        self.channel_process.dependency_observer = (
            lambda snapshot: usage.observe(lease, snapshot)
        )

    def _check_identity(self, params):
        identity = self._identity()
        if any(
            getattr(params, key) != getattr(identity, key)
            for key in ("channel_key", "instance_id", "generation")
        ):
            raise ValueError("STALE_GENERATION")

    async def start(self):
        async with self._lifecycle_lock:
            if self._state_closed:
                result = self.last_stop_result
                if result and "HOST_STATE_IO_PENDING" in result.residual:
                    raise RuntimeError("HOST_STATE_IO_PENDING")
                if result is None or not result.exited or result.residual:
                    raise RuntimeError("CHANNEL_STOP_INCOMPLETE")
            if self._started or not self.enabled:
                return
            if self._text_merge:
                raise RuntimeError("TEXT_MERGE_CLEANUP_PENDING")
            self._text_merge_stopping = False
            self._ingress_open = True
            generation = self.channel_process.health_snapshot()["generation"]
            if generation and self._owner_registry is not None:
                raise RuntimeError("CHANNEL_GENERATION_RETIRED")
            if generation:
                self._launch_spec = replace(
                    self._launch_spec,
                    generation=generation + 1,
                )
            try:
                if self._owner_registry is not None:
                    from ...plugins.dependency_gate import (
                        admit_shared_dependencies,
                    )

                    row = self._registration
                    settings = row.runtime_settings

                    async def audit():
                        return (
                            await self.channel_process.audit(self._launch_spec)
                        ).snapshot

                    await admit_shared_dependencies(
                        audit,
                        plugin_id=row.plugin_id,
                        requirements_file=(
                            row.description_record.requirements_path
                        ),
                        usage_registry=self._owner_registry.dependency_usage,
                        admission_token=row.dependency_token,
                        targets=(
                            *settings.dependency_paths,
                            *(
                                (settings.dependency_install_target,)
                                if settings.dependency_install_target
                                else ()
                            ),
                        ),
                    )
                self.last_stop_result = None
                self._state_closed = False
                await self.channel_process.start(self._launch_spec)
            finally:
                if (
                    self._owner_registry is not None
                    and self.channel_process.dependency_snapshot is not None
                ):
                    self._owner_registry.dependency_usage.observe(
                        self._runtime_lease,
                        self.channel_process.dependency_snapshot,
                    )
            self._started = True
            await self._wait_connected()

    async def _wait_connected(self):
        timeout = (
            self._launch_spec.startup_timeout
            if self._connection_timeout is None
            else self._connection_timeout
        )
        async with asyncio.timeout(timeout):
            while True:
                snapshot = self.channel_process.health_snapshot()
                if (
                    snapshot["state"] == "ready"
                    and snapshot["platform_state"] == "connected"
                ):
                    return
                if snapshot["state"] != "ready" or snapshot[
                    "platform_state"
                ] in {
                    "failed",
                    "disconnected",
                }:
                    raise RuntimeError("CHANNEL_NOT_CONNECTED")
                await asyncio.sleep(0.01)

    async def stop(self):
        self.last_stop_result = None
        self._ingress_open = False
        self.endpoint_service.fence()
        self._text_merge_stopping = True
        if self._admission_wakeup is not None:
            self._admission_wakeup()
        return await run_async_to_completion(self._stop())

    async def _stop(self):
        async with self._lifecycle_lock:
            await self._stop_stream_flushes()
            # Cancel owned requests before retiring their process generation.
            for state in self._text_merge.values():
                if state.timer is not None:
                    state.timer.cancel()
                if state.flush is not None:
                    state.flush.cancel()
            for handle in tuple(self._text_merge):
                await self._cancel_response_text(handle)
            residual = ()
            if self.endpoint_service.forwarder is not None:
                residual = await self.endpoint_service.forwarder.drain(
                    self.endpoint_service,
                    timeout=self._launch_spec.shutdown_timeout,
                )
            try:
                result = await self.channel_process.stop()
            finally:
                # Driver.stop may checkpoint until worker shutdown finishes.
                self._state_closed = True
            try:
                async with asyncio.timeout(self._launch_spec.shutdown_timeout):
                    async with self._state_lock:
                        pass
            except TimeoutError:
                residual = (*residual, "HOST_STATE_IO_PENDING")
            if residual:
                result = replace(
                    result,
                    residual=tuple(
                        dict.fromkeys((*result.residual, *residual)),
                    ),
                )
            self.last_stop_result = result
            if not result.exited or result.residual:
                raise RuntimeError("CHANNEL_STOP_INCOMPLETE")
            self._started = False
            return result

    def set_enqueue_async(self, callback):
        self._enqueue_async = callback
        if callback is None:
            self._ingress_open = False

    async def health_check(self):
        snapshot = self.channel_process.health_snapshot()
        return {
            "channel": self.channel,
            "status": (
                "healthy"
                if snapshot["state"] == "ready"
                and snapshot["platform_state"] == "connected"
                else "unhealthy"
            ),
            **snapshot,
            "error": snapshot["last_error"],
            "last_diagnostic": self._last_diagnostic,
        }

    async def _diagnostic(self, params, notification):
        identity = self._identity().to_mapping()
        if not isinstance(params, dict) or set(params) != {
            *identity,
            "reason_code",
        }:
            raise ValueError("DIAGNOSTIC_INVALID")
        self._check_identity(
            IdentityParams.from_mapping(
                {key: params[key] for key in identity},
            ),
        )
        reason = params["reason_code"]
        if reason not in {
            "HOST_ADMISSION_EXHAUSTED",
            "RESPONSE_FINISH_FAILED",
            "RESPONSE_FINISH_UNKNOWN",
        }:
            raise ValueError("DIAGNOSTIC_INVALID")
        self._record_diagnostic(reason)

    async def _auth_required(self, params, notification):
        if isinstance(params, AuthRequiredParams):
            params = params.to_mapping()
        params = AuthRequiredParams.from_mapping(params)
        self._check_identity(params)
        snapshot = self.channel_process.health_snapshot()
        if (
            AUTH_QRCODE_CAPABILITY not in self.descriptor.capabilities
            or not self.enabled
            or not self._ingress_open
            or self._text_merge_stopping
            or snapshot["state"] != "ready"
            or snapshot["platform_state"] != "connecting"
        ):
            return
        print(
            f"{self.channel} login: scan {params.scan_url}",
            file=sys.stderr,
            flush=True,
        )

    def _record_diagnostic(self, reason):
        self._last_diagnostic = reason
        logger.warning("Channel diagnostic: %s", reason)

    async def _event_batch(self, params, request):
        # RPC cancellation cannot split queue commit from the dedup record.
        return await run_async_to_completion(self._admit_batch(params))

    async def _admit_batch(self, params):
        batch = (
            params
            if isinstance(params, EventBatchParams)
            else EventBatchParams.from_mapping(params)
        )
        accepted, duplicates, rejected = [], [], list(batch.invalid_events)
        async with self._ingress_lock:
            for event in batch.events:
                try:
                    self._check_identity(event)
                except ValueError:
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            "STALE_GENERATION",
                            False,
                        ),
                    )
                    continue
                if (
                    event.actor_unknown
                    and UNKNOWN_ACTOR_CAPABILITY
                    not in self.descriptor.capabilities
                ):
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            "CAPABILITY_REQUIRED",
                            False,
                        ),
                    )
                    continue
                if event.event_id in self._accepted:
                    duplicates.append(event.event_id)
                    continue
                decision_key = (batch.batch_id, event.event_id)
                denied = self._admission_denials.get(decision_key)
                if denied is not None:
                    rejected.append(denied)
                    continue
                try:
                    payload = self._normalize_event(event)
                except ProtocolValidationError:
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            "SCHEMA_MISMATCH",
                            False,
                        ),
                    )
                    continue
                meta = payload["meta"]
                if not self._check_group_mention(
                    bool(meta.get("is_group")),
                    meta,
                ):
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            "MENTION_REQUIRED",
                            False,
                        ),
                    )
                    continue
                if not self._ingress_open:
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            "CHANNEL_STOPPING",
                            True,
                        ),
                    )
                    continue
                if self._enqueue_async is None:
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            "QUEUE_UNAVAILABLE",
                            True,
                        ),
                    )
                    continue
                # Reuse the host ACL store and denial reply before committing
                # admission. Consumption still rechecks changing ACL policy.
                # The same IPC batch retry must not repeat the denial effect;
                # a fresh platform push is a fresh admission decision.
                blocked = await BaseChannel._access_control_gate(self, payload)
                try:
                    self._check_identity(event)
                except ValueError:
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            "STALE_GENERATION",
                            False,
                        ),
                    )
                    continue
                if not self._ingress_open:
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            "CHANNEL_STOPPING",
                            True,
                        ),
                    )
                    continue
                if blocked:
                    denial = RejectedEvent(
                        event.event_id,
                        "ACCESS_DENIED",
                        False,
                    )
                    self._admission_denials[decision_key] = denial
                    while len(self._admission_denials) > 4096:
                        self._admission_denials.popitem(last=False)
                    rejected.append(denial)
                    continue
                try:
                    result = await self._enqueue_async(payload)
                except Exception:
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            "QUEUE_UNAVAILABLE",
                            True,
                        ),
                    )
                    continue
                if not result.accepted:
                    rejected.append(
                        RejectedEvent(
                            event.event_id,
                            result.reason_code,
                            result.retryable,
                        ),
                    )
                    continue
                self._accepted[event.event_id] = None
                while len(self._accepted) > 4096:
                    self._accepted.popitem(last=False)
                accepted.append(event.event_id)
        return EventBatchAck(
            tuple(accepted),
            tuple(duplicates),
            tuple(rejected),
            batch.batch_id,
        ).to_mapping()

    def _state_path(self):
        if self._workspace_dir is None:
            return None
        scope = hashlib.sha256(
            (self.channel + ":" + self._launch_spec.instance_id).encode(),
        ).hexdigest()
        return self._workspace_dir / "channel_state" / (scope + ".json")

    def _check_state_open(self, params):
        self._check_identity(params)
        if self._state_closed:
            raise ValueError("CHANNEL_STOPPING")

    async def _host_state(self, operation, params):
        params = (
            params
            if isinstance(params, HostStateParams)
            else HostStateParams.from_mapping(params)
        )
        self._check_state_open(params)
        async with self._state_lock:
            self._check_state_open(params)
            return await run_sync_io(
                self._state_operation,
                operation,
                params,
            )

    async def _host_receipt(self, operation, params):
        params = (
            params
            if isinstance(params, HostStateParams)
            else HostStateParams.from_mapping(params)
        )
        self._check_state_open(params)
        if params.schema_version != 1 or operation not in {"get", "put"}:
            raise ValueError("RESPONSE_RECEIPT_VERSION")
        async with self._state_lock:
            self._check_state_open(params)
            return await run_sync_io(
                self._receipt_operation,
                operation,
                params,
            )

    def _receipt_operation(self, operation, params):
        from ...channel_protocol.response_receipts import ResponseReceiptStore

        path = self._state_path()
        if path is None:
            raise ValueError("WORKSPACE_IDENTITY_REQUIRED")
        store = ResponseReceiptStore(path.with_suffix(".receipts.sqlite3"))
        if operation == "get":
            return {"value": store.get(params.key)}
        store.put(params.key, params.value)
        return {"stored": True}

    def _state_operation(self, operation, params):
        path = self._state_path()
        if path is not None:
            try:
                with path.open("rb") as source:
                    raw = source.read(_STATE_MAX_BYTES + 1)
            except FileNotFoundError:
                self._state = {}
            else:
                if len(raw) > _STATE_MAX_BYTES:
                    raise ValueError("HOST_STATE_CAPACITY")
                restored = json.loads(raw)
                if (
                    not isinstance(restored, dict)
                    or len(restored) > _STATE_MAX_KEYS
                ):
                    raise ValueError("HOST_STATE_INVALID")
                if any(
                    not isinstance(row, dict)
                    or set(row) != {"schema_version", "value"}
                    or type(row["schema_version"]) is not int
                    or row["schema_version"] < 1
                    for row in restored.values()
                ):
                    raise ValueError("HOST_STATE_INVALID")
                self._state = restored
        key = params.key
        if operation == "get":
            row = self._state.get(key)
            if row and row["schema_version"] != params.schema_version:
                raise ValueError("HOST_STATE_VERSION")
            return {"value": row["value"] if row else None}
        updated = dict(self._state)
        if operation == "delete":
            updated.pop(key, None)
        else:
            updated[key] = {
                "schema_version": params.schema_version,
                "value": params.value,
            }
        raw = json.dumps(updated, ensure_ascii=False, allow_nan=False).encode()
        if len(updated) > _STATE_MAX_KEYS or len(raw) > _STATE_MAX_BYTES:
            raise ValueError("HOST_STATE_CAPACITY")
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=path.parent,
                    delete=False,
                ) as output:
                    temporary = Path(output.name)
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        self._state = updated
        return {"stored": True}

    def _debounce_payload(self, payload):
        ready = super()._debounce_payload(payload)
        if isinstance(payload, dict):
            meta = payload.setdefault("meta", {})
        else:
            meta = getattr(payload, "channel_meta", None)
            if meta is None:
                meta = {}
                payload.channel_meta = meta
        session_id = self.get_debounce_key(payload)
        if ready:
            handles = self._buffered_handles.pop(session_id, [])
            if handles:
                meta["_merged_response_handles"] = list(
                    dict.fromkeys(
                        [
                            *handles,
                            *(meta.get("_merged_response_handles") or []),
                        ],
                    ),
                )
        else:
            handles = self._buffered_handles.setdefault(session_id, [])
            for handle in [
                *meta.get("_merged_response_handles", []),
                meta.get("response_handle"),
            ]:
                if handle and handle not in handles:
                    handles.append(handle)
        return ready

    def merge_native_items(self, items):
        if not items:
            return None
        meta = dict(items[-1].get("meta") or {})
        handles = []
        for item in items:
            current = item.get("meta") or {}
            handles.extend(current.get("_merged_response_handles") or [])
            if current.get("response_handle"):
                handles.append(current["response_handle"])
        meta["_merged_response_handles"] = list(dict.fromkeys(handles))
        return {
            **items[0],
            **items[-1],
            "acl_sender_id": items[0].get("acl_sender_id", ""),
            "content_parts": [
                part
                for item in items
                for part in item.get("content_parts", [])
            ],
            "meta": meta,
        }

    def build_agent_request_from_native(self, native_payload):
        meta = dict(native_payload.get("meta") or {})
        actor_unknown = native_payload.get("actor_unknown") is True
        if actor_unknown and (
            UNKNOWN_ACTOR_CAPABILITY not in self.descriptor.capabilities
            or any(
                value != ""
                for value in (
                    native_payload.get("sender_id"),
                    native_payload.get("acl_sender_id"),
                    native_payload.get("user_id"),
                    meta.get("user_id"),
                )
            )
        ):
            raise ProtocolValidationError("Invalid anonymous actor")
        user_id = (
            native_payload.get("user_id")
            or meta.get("user_id")
            or native_payload.get("sender_id", "")
        )
        query = self._extract_query_from_payload(native_payload)
        approval_command = False
        source_request_id = ""
        if query.lstrip().startswith("/"):
            from qwenpaw.runtime.commands.control import (
                _COMMAND_REGISTRY,
                _extract_command_token,
                ApprovalCommandHandler,
                ApproveCommandHandler,
                DenyCommandHandler,
            )

            if isinstance(
                _COMMAND_REGISTRY.get(_extract_command_token(query)),
                (
                    ApprovalCommandHandler,
                    ApproveCommandHandler,
                    DenyCommandHandler,
                ),
            ):
                approval_command = True
                user_id = str(
                    native_payload.get("acl_sender_id") or "",
                ).strip()
                if not user_id:
                    raise ValueError("APPROVAL_OPERATOR_UNAVAILABLE")
                from qwenpaw.runtime.commands.control import parse_args

                token = _extract_command_token(query)
                args = parse_args(query.lstrip(), token)
                source_request_id = args.get("request_id", "")
                if token.lower() in {"/approve", "/deny"}:
                    source_request_id = next(
                        (
                            part
                            for part in args.get("_raw_args", "").split()
                            if not part.startswith("--")
                        ),
                        "",
                    )
        request = self.build_agent_request_from_user_content(
            channel_id=self.channel,
            sender_id=user_id,
            session_id=native_payload.get("session_id")
            or self.resolve_session_id(user_id, meta),
            content_parts=native_payload.get("content_parts") or [],
            channel_meta=meta,
        )
        request.channel_meta = meta
        request._channel_actor_unknown = actor_unknown
        if approval_command:
            from qwenpaw._control_state import (
                ControlRequestBinding,
                ControlCommandState,
            )

            request.root_session_id = (
                meta.get("root_session_id") or request.session_id
            )
            handle = meta.get("response_handle")
            if handle:
                try:
                    request._channel_control_state = ControlCommandState(
                        ControlRequestBinding(
                            command_request_id=uuid.uuid4().hex,
                            **self._identity().to_mapping(),
                            response_handle=handle,
                            session_id=request.session_id,
                            root_session_id=request.root_session_id,
                            user_id=user_id,
                            agent_id=getattr(self._workspace, "agent_id", None)
                            or "default",
                            source_request_id=source_request_id,
                        ),
                    )
                except ValueError:
                    pass
        return request

    def resolve_session_id(self, sender_id, channel_meta=None):
        value = (channel_meta or {}).get("session_id")
        if value:
            return value
        return super().resolve_session_id(sender_id, channel_meta)

    def get_debounce_key(self, payload):
        if not isinstance(payload, dict):
            return super().get_debounce_key(payload)
        value = (payload.get("meta") or {}).get("debounce_key")
        if not isinstance(value, str) or not value.strip():
            raise ProtocolValidationError("Standard debounce_key required")
        return value

    def to_handle_from_target(self, *, user_id, session_id):
        return encode_reply_target(user_id=user_id, session_id=session_id)

    def get_to_handle_from_request(self, request):
        meta = getattr(request, "channel_meta", None) or {}
        return meta.get("response_handle") or self.to_handle_from_target(
            user_id=request.user_id,
            session_id=request.session_id,
        )

    def get_on_reply_sent_args(self, request, to_handle):
        return request.user_id, request.session_id

    def _require_enabled(self):
        if not self.enabled:
            raise _ChannelLifecycleError(
                OutboundResult(
                    "disabled",
                    DeliveryState.FAILED,
                    "CHANNEL_DISABLED",
                ),
            )

    async def _route(self, to_handle, meta):
        self._require_enabled()
        await self._wait_connected()
        if meta.get("response_handle"):
            return meta["response_handle"]
        try:
            result = await self.channel_process.call(
                "channel.response.open",
                {
                    **self._identity().to_mapping(),
                    "to_handle": to_handle,
                    # Local policy cache contains a DTO; route metadata is
                    # pure wire data. Keep the cache for unknown retry locally.
                    "meta": {
                        key: value
                        for key, value in meta.items()
                        if key not in {"_response_policy", "_text_merge_error"}
                    },
                },
            )
        except RpcError as exc:
            if exc.code == RPC_RESPONSE_OPEN_FAILED:
                raise _ResponseOpenDeliveryError(exc) from exc
            if _rpc_result_unknown(exc):
                meta["_reply_unknown"] = True
                raise ChannelDeliveryError(
                    OutboundResult(
                        "unroutable",
                        DeliveryState.UNKNOWN,
                        "PLATFORM_RESULT_UNKNOWN",
                    ),
                ) from exc
            if (
                isinstance(exc.data, dict)
                and exc.data.get("reason_code") == "OUTBOUND_TARGET_UNKNOWN"
            ):
                raise ChannelDeliveryError(
                    OutboundResult(
                        "unroutable",
                        DeliveryState.FAILED,
                        "OUTBOUND_TARGET_UNKNOWN",
                    ),
                ) from exc
            raise
        meta["response_handle"] = result["response_handle"]
        return result["response_handle"]

    async def _send_operation(
        self,
        to_handle,
        meta,
        operation,
        *,
        _format_entry=None,
        **fields,
    ):
        self._require_enabled()
        meta = meta if meta is not None else {}
        if self._response_context.get() is None and not meta.get(
            "response_handle",
        ):
            try:
                async with self._response_scope(meta):
                    return await self._send_operation_owned(
                        to_handle,
                        meta,
                        operation,
                        _format_entry=_format_entry,
                        **fields,
                    )
            finally:
                if not meta.get("_reply_unknown"):
                    meta.pop("response_handle", None)
        return await self._send_operation_owned(
            to_handle,
            meta,
            operation,
            _format_entry=_format_entry,
            **fields,
        )

    def _format_send_fields(
        self,
        fields,
        meta,
        policy,
        entry,
        *,
        strip_text=False,
    ):
        if entry == "direct":
            prefix = (
                (meta.get("bot_prefix") or self.bot_prefix)
                if policy.direct_prefix
                else ""
            )
            separator = ""
        else:
            prefix = (
                meta.get("bot_prefix") if policy.parts_metadata_prefix else ""
            ) or (self.bot_prefix if policy.parts_configured_prefix else "")
            separator = "  "
        prefixed = []
        for part in fields["content_parts"]:
            if strip_text and part.get("type") == "text":
                part = {**part, "text": part["text"].strip()}
            if (
                prefix
                and part.get("type") == "text"
                and (not strip_text or part["text"])
            ):
                part = {**part, "text": prefix + separator + part["text"]}
                if entry == "parts" and policy.parts_preserve_order:
                    prefix = ""
            prefixed.append(part)
        return {**fields, "content_parts": prefixed}

    async def _send_operation_owned(
        self,
        to_handle,
        meta,
        operation,
        *,
        _format_entry=None,
        **fields,
    ):
        self._require_enabled()
        scope = self._response_context.get()
        if scope is not None:
            scope["meta"] = meta
        route = await self._route(to_handle, meta)
        deferred_format = None
        if _format_entry is not None:
            response_policy = await self._response_policy(to_handle, meta)
            policy = response_policy.send_format or SendFormatPolicy()
            if (
                TEXT_MERGE_CAPABILITY in self.descriptor.capabilities
                and response_policy.text_merge_delay_ms is not None
                and response_policy.text_merge_format_on_flush
                and _format_entry == "parts"
                and operation == "message.create"
                and fields.get("content_source") != "event"
                and fields.get("approval") is None
                and fields.get("approval_resolution") is None
                and fields.get("content_parts")
                and all(
                    part.get("type") == "text"
                    for part in fields["content_parts"]
                )
            ):
                deferred_format = policy
            else:
                fields = self._format_send_fields(
                    fields,
                    meta,
                    policy,
                    _format_entry,
                )
        if TEXT_MERGE_CAPABILITY in self.descriptor.capabilities:
            policy = await self._response_policy(to_handle, meta)
            if policy.text_merge_delay_ms is not None:
                parts = fields.get("content_parts")
                mergeable = (
                    operation == "message.create"
                    and fields.get("content_source") != "event"
                    and fields.get("approval") is None
                    and fields.get("approval_resolution") is None
                    and parts
                )
                if mergeable and all(
                    part.get("type") == "text" for part in parts
                ):
                    await self._buffer_response_text(
                        to_handle,
                        meta,
                        fields,
                        separator_newlines=(
                            policy.text_merge_separator_newlines
                        ),
                        format_policy=deferred_format,
                    )
                    return None
                independent_media = (
                    mergeable
                    and not policy.text_merge_flush_before_media
                    and not (
                        policy.send_format
                        and policy.send_format.parts_preserve_order
                    )
                    and all(
                        part.get("type") in {"image", "video", "file", "audio"}
                        for part in parts
                    )
                )
                if not independent_media:
                    await self._flush_response_text(route)
        return await self._send_operation_immediate(
            to_handle,
            meta,
            operation,
            **fields,
        )

    async def _send_operation_immediate(
        self,
        to_handle,
        meta,
        operation,
        **fields,
    ):
        route = meta["response_handle"]
        fingerprint = hashlib.sha256(
            json.dumps([route, operation, fields], sort_keys=True).encode(),
        ).hexdigest()
        pending = meta.get("_pending_delivery")
        if meta.get("_reply_unknown") and (
            not pending or pending["fingerprint"] != fingerprint
        ):
            raise ChannelDeliveryError(
                OutboundResult(
                    "unsettled",
                    DeliveryState.UNKNOWN,
                    "PLATFORM_RESULT_UNKNOWN",
                ),
            )
        delivery_id = (
            pending["delivery_id"]
            if pending and pending["fingerprint"] == fingerprint
            else uuid.uuid4().hex
        )
        meta["_pending_delivery"] = {
            "delivery_id": delivery_id,
            "fingerprint": fingerprint,
        }
        if "approval_resolution" in fields:
            meta["_pending_delivery"]["payload"] = {
                "to_handle": route,
                "operation": operation,
                **fields,
            }
        self._require_enabled()
        await update_outbound_media(
            self._workspace_dir,
            fields.get("content_parts", []),
            delivery_id,
            pending=True,
        )
        try:
            result = OutboundResult.from_mapping(
                await self.channel_process.call(
                    "channel.send",
                    {
                        **self._identity().to_mapping(),
                        "delivery_id": delivery_id,
                        "to_handle": route,
                        "operation": operation,
                        **fields,
                    },
                ),
            )
            if result.state.value != "acknowledged":
                error = ChannelDeliveryError(result)
                if error.side_effect_possible:
                    meta["_reply_unknown"] = True
                else:
                    meta.pop("_pending_delivery", None)
                    await update_outbound_media(
                        self._workspace_dir,
                        fields.get("content_parts", []),
                        delivery_id,
                        pending=False,
                    )
                raise error
        except (ChannelCallUnknown, asyncio.CancelledError):
            meta["_reply_unknown"] = True
            raise
        except RpcError as exc:
            if _rpc_result_unknown(exc):
                meta["_reply_unknown"] = True
            raise
        meta.pop("_pending_delivery", None)
        meta["_last_delivery_id"] = delivery_id
        await update_outbound_media(
            self._workspace_dir,
            fields.get("content_parts", []),
            delivery_id,
            pending=False,
        )
        return delivery_id

    def _check_text_state(self, state):
        if state.error is not None:
            raise state.error
        if (
            state.closed
            or self._text_merge_stopping
            or state.identity != self._identity().to_mapping()
        ):
            raise ValueError("STALE_GENERATION")

    async def _buffer_response_text(
        self,
        to_handle,
        meta,
        fields,
        *,
        separator_newlines=1,
        format_policy=None,
    ):
        handle = meta["response_handle"]
        if meta.get("_reply_unknown"):
            raise ChannelDeliveryError(
                OutboundResult(
                    "unsettled",
                    DeliveryState.UNKNOWN,
                    "PLATFORM_RESULT_UNKNOWN",
                ),
            )
        if meta.get("_text_merge_error") is not None:
            raise meta["_text_merge_error"]
        if self._text_merge_stopping:
            raise ValueError("STALE_GENERATION")
        state = self._text_merge.get(handle)
        if state is None:
            if len(self._text_merge) >= _TEXT_MERGE_MAX_RESPONSES:
                error = ValueError("TEXT_MERGE_CAPACITY")
                meta["_text_merge_error"] = error
                raise error
            state = _ResponseText(
                to_handle,
                meta,
                self._identity().to_mapping(),
            )
            self._text_merge[handle] = state
        while True:
            async with state.lock:
                self._check_text_state(state)
                task = state.flush
                if task is None:
                    candidate = deepcopy(fields)
                    candidate["content_parts"] = [
                        {
                            "type": "text",
                            "text": "\n".join(
                                p["text"] for p in fields["content_parts"]
                            ),
                        },
                    ]
                    previous = state.fields
                    if previous is not None and (
                        {
                            k: v
                            for k, v in previous.items()
                            if k != "content_parts"
                        }
                        != {
                            k: v
                            for k, v in candidate.items()
                            if k != "content_parts"
                        }
                        or (state.raw_text is not None)
                        != (format_policy is not None)
                    ):
                        # Differing source/operation attributes are a boundary;
                        # neither batch may silently inherit the other's shape.
                        task = self._begin_text_flush(handle, state)
                    else:
                        if previous is not None:
                            candidate["content_parts"][0]["text"] = (
                                (
                                    state.raw_text
                                    if format_policy is not None
                                    else previous["content_parts"][0]["text"]
                                )
                                + "\n" * separator_newlines
                                + candidate["content_parts"][0]["text"]
                            )
                        raw_text = None
                        if format_policy is not None:
                            raw_text = candidate["content_parts"][0]["text"]
                            candidate = self._format_send_fields(
                                candidate,
                                meta,
                                format_policy,
                                "parts",
                                strip_text=format_policy.parts_strip_text,
                            )
                        size = len(
                            json.dumps(
                                {
                                    **state.identity,
                                    "delivery_id": "0" * 32,
                                    "to_handle": handle,
                                    "operation": "message.create",
                                    **candidate,
                                },
                                ensure_ascii=False,
                                allow_nan=False,
                                separators=(",", ":"),
                            ).encode("utf-8"),
                        )
                        if raw_text is not None:
                            size += len(raw_text.encode("utf-8"))
                        if (
                            self._text_merge_bytes - state.size + size
                            > _TEXT_MERGE_MAX_BYTES
                        ):
                            state.error = ValueError("TEXT_MERGE_CAPACITY")
                            meta["_text_merge_error"] = state.error
                            raise state.error
                        self._text_merge_bytes += size - state.size
                        state.fields, state.size = candidate, size
                        state.raw_text = raw_text
                        if state.timer is not None:
                            state.timer.cancel()
                            await self._await_text_task(state.timer)
                            state.timer = None
                        cached = meta.get("_response_policy")
                        delay = cached[1].text_merge_delay_ms if cached else 0
                        if delay:
                            state.timer = asyncio.create_task(
                                self._text_timer(handle, state, delay / 1000),
                                name="channel-text-merge",
                            )
                        return
            await asyncio.shield(task)

    async def _text_timer(self, handle, state, delay):
        try:
            await asyncio.sleep(delay)
            await self._flush_response_text(handle)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Timer errors are rethrown by the next send/finish, never lost.
            state.error = exc

    def _begin_text_flush(self, handle, state):
        if state.flush is None:
            state.flush = asyncio.create_task(
                self._send_text_batch(handle, state),
                name="channel-text-flush",
            )
        return state.flush

    async def _send_text_batch(self, handle, state):
        try:
            self._check_text_state(state)
            if (
                state.raw_text is None
                or state.fields["content_parts"][0]["text"]
            ):
                await self._send_operation_immediate(
                    state.to_handle,
                    state.meta,
                    "message.create",
                    **state.fields,
                )
        except BaseException as exc:
            state.error = (
                ChannelDeliveryError(
                    OutboundResult(
                        "unsettled",
                        DeliveryState.UNKNOWN,
                        "PLATFORM_RESULT_UNKNOWN",
                    ),
                )
                if isinstance(exc, asyncio.CancelledError)
                else exc
            )
            if (
                isinstance(exc, ChannelDeliveryError)
                and not exc.side_effect_possible
            ):
                self._text_merge_bytes -= state.size
                state.fields, state.size = None, 0
                state.raw_text = None
            raise
        else:
            self._text_merge_bytes -= state.size
            state.fields, state.size = None, 0
            state.raw_text = None
        finally:
            state.flush = None

    async def _flush_response_text(self, response_handle):
        state = self._text_merge.get(response_handle)
        if state is None:
            return
        async with state.lock:
            self._check_text_state(state)
            if state.timer is not None:
                timer, state.timer = state.timer, None
                if timer is not asyncio.current_task():
                    timer.cancel()
                    await self._await_text_task(timer)
            task = state.flush
            if task is None and state.fields is not None:
                task = self._begin_text_flush(response_handle, state)
        if task is not None:
            await asyncio.shield(task)

    @staticmethod
    async def _await_text_task(task):
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.cancelled() or asyncio.current_task().cancelling():
                raise

    async def _cancel_response_text(self, response_handle):
        state = self._text_merge.get(response_handle)
        if state is None:
            return
        async with state.lock:
            state.closed = True
            if state.timer is not None:
                state.timer.cancel()
                await self._await_text_task(state.timer)
                state.timer = None
            task = state.flush
        if task is not None:
            try:
                await self._await_text_task(task)
            except Exception as exc:
                if state.error is not exc:
                    raise
        # Only settled work releases capacity, including an explicitly
        # cancelled unknown batch. The child journal still owns its receipt.
        async with state.lock:
            if self._text_merge.get(response_handle) is state:
                self._text_merge_bytes -= state.size
                state.size = 0
                state.raw_text = None
                self._text_merge.pop(response_handle)

    async def _finish_route(self, meta, outcome):
        if (
            outcome != "cancelled"
            and meta.get("_text_merge_error") is not None
        ):
            raise meta["_text_merge_error"]
        handles = list(meta.get("_merged_response_handles") or [])
        if meta.get("response_handle"):
            handles.append(meta["response_handle"])
        failure = None
        for handle in dict.fromkeys(handles):
            try:
                if outcome == "cancelled":
                    await self._cancel_response_text(handle)
                else:
                    try:
                        await self._flush_response_text(handle)
                    except ChannelDeliveryError as exc:
                        state = self._text_merge.get(handle)
                        if not (
                            outcome == "failed"
                            and exc.state == "failed"
                            and not exc.side_effect_possible
                            and state is not None
                            and state.error is exc
                            and state.fields is None
                            and state.size == 0
                            and state.flush is None
                            and state.identity == self._identity().to_mapping()
                        ):
                            raise
                        # The caller still receives the original send error.
                        # This exact batch has settled without an effect, so
                        # failed finish must release its child route/typing.
                await self.channel_process.call(
                    "channel.response.finish",
                    {
                        **self._identity().to_mapping(),
                        "response_handle": handle,
                        "outcome": outcome,
                    },
                    # Cancellation closeout retains its control allowance;
                    # ordinary finish may perform a full native cleanup.
                    **({"timeout": 5.0} if outcome == "cancelled" else {}),
                )
                await self._cancel_response_text(handle)
            except Exception as exc:
                failure = exc
        if failure is not None:
            raise failure

    async def send(self, to_handle, text, meta=None):
        meta = meta if meta is not None else {}
        await self._send_operation(
            to_handle,
            meta,
            "message.create",
            _format_entry="direct",
            **self._content_source_fields("direct"),
            content_parts=[{"type": "text", "text": text}],
        )

    def _content_source_fields(self, source):
        if CONTENT_SOURCE_CAPABILITY in self.descriptor.capabilities:
            return {"content_source": source}
        return {}

    async def send_media(self, to_handle, part, meta=None):
        self._require_enabled()
        value = (
            dict(part)
            if isinstance(part, dict)
            else part.model_dump(mode="json", exclude_none=True)
        )
        if value.get("type") not in {"image", "video", "file", "audio"}:
            raise ProtocolValidationError("Media part required")
        locator = (
            "data" if value["type"] == "audio" else value["type"] + "_url"
        )
        value = validate_content_part(
            {
                key: value[key]
                for key in ("type", locator, "filename", "mime_type", "format")
                if key in value
            },
        )
        await self._send_operation(
            to_handle,
            meta if meta is not None else {},
            "message.create",
            content_parts=[value],
            **self._content_source_fields("media"),
        )

    async def send_content_parts(self, to_handle, parts, meta=None):
        self._require_enabled()
        meta = meta if meta is not None else {}
        normalized = []
        for part in parts:
            value = (
                dict(part)
                if isinstance(part, dict)
                else part.model_dump(mode="json", exclude_none=True)
            )
            kind = value.get("type")
            if kind in {"text", "refusal"}:
                if body := value.get("text") or value.get("refusal"):
                    normalized.append({"type": "text", "text": body})
            elif kind in {"image", "file", "audio", "video"}:
                locator = "data" if kind == "audio" else kind + "_url"
                normalized.append(
                    {
                        key: value[key]
                        for key in (
                            "type",
                            locator,
                            "filename",
                            "mime_type",
                            "format",
                        )
                        if key in value
                    },
                )
        if not normalized:
            return None
        if self._response_context.get() is None and not meta.get(
            "response_handle",
        ):
            try:
                async with self._response_scope(meta):
                    return await self._send_parts_owned(
                        to_handle,
                        normalized,
                        meta,
                    )
            finally:
                if not meta.get("_reply_unknown"):
                    meta.pop("response_handle", None)
        return await self._send_parts_owned(to_handle, normalized, meta)

    async def _send_parts_owned(self, to_handle, parts, meta):
        response_policy = await self._response_policy(to_handle, meta)
        policy = response_policy.send_format or SendFormatPolicy()
        if policy.parts_preserve_order:
            outgoing = self._ordered_content_parts(
                parts,
                policy.parts_strip_text,
            )
            if not outgoing:
                return None
            # A mixed operation reaches the existing media boundary, which
            # flushes prior buffered text before dispatching this exact order.
            return await self._send_operation(
                to_handle,
                meta,
                "message.create",
                _format_entry="parts",
                **self._content_source_fields("content_parts"),
                content_parts=outgoing,
            )
        body = "\n".join(p["text"] for p in parts if p["type"] == "text")
        media = [p for p in parts if p["type"] != "text"]
        if policy.parts_strip_text and not (
            response_policy.text_merge_delay_ms is not None
            and response_policy.text_merge_format_on_flush
        ):
            body = body.strip()
        if response_policy.text_merge_delay_ms is not None and body and media:
            await self._send_operation(
                to_handle,
                meta,
                "message.create",
                _format_entry="parts",
                **self._content_source_fields("content_parts"),
                content_parts=[{"type": "text", "text": body}],
            )
            # The route policy chooses whether media flushes buffered text.
            body = ""
        outgoing = ([{"type": "text", "text": body}] if body else []) + media
        if not outgoing:
            return None
        result = await self._send_operation(
            to_handle,
            meta,
            "message.create",
            _format_entry="parts",
            **self._content_source_fields("content_parts"),
            content_parts=outgoing,
        )
        return result

    @staticmethod
    def _ordered_content_parts(parts, strip_text):
        outgoing, texts = [], []

        def flush_text():
            body = "\n".join(texts)
            texts.clear()
            if strip_text:
                body = body.strip()
            if body:
                outgoing.append({"type": "text", "text": body})

        for part in parts:
            if part["type"] == "text":
                texts.append(part["text"])
            else:
                flush_text()
                outgoing.append(part)
        flush_text()
        return outgoing

    async def _access_control_gate(self, payload):
        blocked = await super()._access_control_gate(payload)
        if blocked:
            meta = (
                payload.get("meta", {})
                if isinstance(payload, dict)
                else getattr(payload, "channel_meta", {})
            )
            await self._finish_route(meta, "completed")
        return blocked

    async def _on_consume_error(self, request, to_handle, err_text):
        scope = self._response_context.get()
        meta = (
            scope["meta"]
            if scope is not None
            else getattr(request, "channel_meta", None) or {}
        )
        request.channel_meta = meta
        meta["_reply_failed"] = True
        await self._flush_response_text(meta.get("response_handle"))
        if not meta.get("_reply_unknown"):
            await super()._on_consume_error(request, to_handle, err_text)
            await self._flush_response_text(meta.get("response_handle"))

    async def _response_policy(self, to_handle, meta):
        route = await self._route(to_handle, meta)
        cached = meta.get("_response_policy")
        if cached is not None and cached[0] == route:
            return cached[1]
        value = await self.channel_process.call(
            "channel.response.describe",
            {**self._identity().to_mapping(), "response_handle": route},
        )
        capabilities = self.descriptor.capabilities
        if (
            isinstance(value, dict)
            and set(value)
            & {
                "text_merge_delay_ms",
                "text_merge_flush_before_media",
                "text_merge_separator_newlines",
                "text_merge_format_on_flush",
            }
            and TEXT_MERGE_CAPABILITY not in capabilities
        ):
            raise ProtocolValidationError(
                "Text merge capability was not declared",
                reason_code="CAPABILITY_REQUIRED",
            )
        policy = ResponsePolicy.from_mapping(value)
        if (
            "raw_completed_text" in value
            and RAW_COMPLETED_TEXT_CAPABILITY not in capabilities
        ):
            raise ProtocolValidationError(
                "Raw completed text capability was not declared",
                reason_code="CAPABILITY_REQUIRED",
            )
        policy = ResponsePolicy(
            streaming=policy.streaming
            and "streaming" in capabilities
            and self.streaming_enabled,
            prepare=policy.prepare and "response.prepare" in capabilities,
            completion_reaction=policy.completion_reaction
            and "reaction" in capabilities,
            send_format=policy.send_format,
            text_merge_delay_ms=policy.text_merge_delay_ms,
            continue_on_delivery_error=policy.continue_on_delivery_error,
            raw_completed_text=policy.raw_completed_text,
            text_merge_flush_before_media=policy.text_merge_flush_before_media,
            text_merge_separator_newlines=policy.text_merge_separator_newlines,
            text_merge_format_on_flush=policy.text_merge_format_on_flush,
        )
        meta["_response_policy"] = (route, policy)
        return policy

    async def _before_consume_process(self, request):
        self._require_enabled()
        scope = self._response_context.get()
        meta = getattr(request, "channel_meta", None) or {}
        request.channel_meta = meta
        if scope is not None:
            scope["meta"] = meta
        if meta.get("_reply_unknown"):
            raise ChannelDeliveryError(
                OutboundResult(
                    "unsettled",
                    DeliveryState.UNKNOWN,
                    "PLATFORM_RESULT_UNKNOWN",
                ),
            )
        if not (
            await self._response_policy(
                self.get_to_handle_from_request(request),
                meta,
            )
        ).prepare:
            return
        route = await self._route(
            self.get_to_handle_from_request(request),
            meta,
        )
        failed = meta.get("_response_prepare_failure")
        if failed is not None and failed["response_handle"] == route:
            return
        self._require_enabled()
        try:
            result = OutboundResult.from_mapping(
                await self.channel_process.call(
                    "channel.response.prepare",
                    {
                        **self._identity().to_mapping(),
                        "response_handle": route,
                        "delivery_id": hashlib.sha256(
                            (route + ":prepare").encode(),
                        ).hexdigest(),
                    },
                ),
            )
            if result.state.value != "acknowledged":
                error = ChannelDeliveryError(result)
                if error.side_effect_possible:
                    meta["_reply_unknown"] = True
                    raise error
                meta["_response_prepare_failure"] = {
                    "response_handle": route,
                    "result": result.to_mapping(),
                }
                self._record_diagnostic(error.reason_code)
                return
        except (ChannelCallUnknown, asyncio.CancelledError):
            meta["_reply_unknown"] = True
            raise
        except RpcError as exc:
            if _rpc_result_unknown(exc):
                meta["_reply_unknown"] = True
            raise

    def _stream_text(self, stream_type, text, meta, send_format=None):
        if stream_type == "reasoning" and text:
            text = "💭 " + text
        prefix = (
            meta.get("bot_prefix") or self.bot_prefix
            if (send_format or SendFormatPolicy()).stream_prefix
            else ""
        )
        return prefix + "  " + text if prefix and text else text

    def _stream_flush_timeout(self):
        # The supervisor bounds each outbound RPC by the selected send budget
        # plus receipt margin. Base must join that same operation unchanged.
        return None

    async def on_streaming_start(
        self,
        request,
        to_handle,
        event,
        send_meta,
        stream_type,
        accumulated_text="",
    ):
        policy = await self._response_policy(to_handle, send_meta)
        if not policy.streaming:
            return
        try:
            delivery = await self._send_operation(
                to_handle,
                send_meta,
                "stream.start",
                stream_type=stream_type,
                sequence=0,
                accumulated_text=self._stream_text(
                    stream_type,
                    "...",
                    send_meta,
                    policy.send_format,
                ),
            )
        except ChannelDeliveryError as exc:
            if exc.side_effect_possible:
                raise
            return
        send_meta.setdefault("_isolated_streams", {})[stream_type] = {
            "delivery_id": delivery,
            "sequence": 0,
            "last_preview_at": None,
        }

    async def on_streaming_delta(
        self,
        request,
        to_handle,
        event,
        send_meta,
        stream_type,
        accumulated_text="",
    ):
        state = send_meta.get("_isolated_streams", {}).get(stream_type)
        if state:
            now = time.monotonic()
            previous = state.get("last_preview_at")
            if (
                state.get("preview_full")
                or previous is not None
                and now - previous < 0.2
            ):
                return
            state["last_preview_at"] = now
            policy = await self._response_policy(to_handle, send_meta)
            state["sequence"] += 1
            try:
                await self._send_operation(
                    to_handle,
                    send_meta,
                    "stream.delta",
                    stream_type=stream_type,
                    target_delivery_id=state["delivery_id"],
                    sequence=state["sequence"],
                    accumulated_text=self._stream_text(
                        stream_type,
                        accumulated_text,
                        send_meta,
                        policy.send_format,
                    ),
                )
            except ChannelDeliveryError as exc:
                if (
                    exc.state != "failed"
                    or exc.reason_code != "RESPONSE_STATE_CAPACITY"
                ):
                    raise
                state["preview_full"] = True

    async def on_streaming_end(
        self,
        request,
        to_handle,
        event,
        send_meta,
        stream_type,
        accumulated_text="",
    ):
        state = send_meta.get("_isolated_streams", {}).get(stream_type)
        if state:
            policy = await self._response_policy(to_handle, send_meta)
            state["sequence"] += 1
            await self._send_operation(
                to_handle,
                send_meta,
                "stream.end",
                stream_type=stream_type,
                target_delivery_id=state["delivery_id"],
                sequence=state["sequence"],
                accumulated_text=self._stream_text(
                    stream_type,
                    accumulated_text,
                    send_meta,
                    policy.send_format,
                ),
            )
            send_meta["_last_delivery_id"] = state["delivery_id"]
            send_meta["_isolated_streams"].pop(stream_type, None)
        elif accumulated_text.strip():
            text = (
                f"💭 {accumulated_text}"
                if stream_type == "reasoning"
                else accumulated_text
            )
            await self.send_content_parts(
                to_handle,
                [{"type": "text", "text": text}],
                send_meta,
            )

    async def on_event_message_completed(
        self,
        request,
        to_handle,
        event,
        send_meta,
    ):
        scope = self._response_context.get()
        if scope is not None:
            scope.pop("ordinary_event", None)
        if await self._send_control_resolution(
            request,
            to_handle,
            event,
            send_meta,
        ):
            return
        metadata = getattr(event, "metadata", None) or {}
        metadata = metadata.get("metadata", metadata)
        if metadata.get(
            "message_type",
        ) == "tool_guard_approval" and metadata.get("approval_request_id"):
            content = getattr(event, "content", None) or []
            body = (
                content
                if isinstance(content, str)
                else "".join(
                    (
                        part.get("text", "")
                        if isinstance(part, dict)
                        else getattr(part, "text", "")
                    )
                    for part in content
                )
            )
            await self._send_operation(
                to_handle,
                send_meta,
                "message.create",
                approval=_approval_card_params(metadata),
                content_parts=[{"type": "text", "text": body}],
            )
        else:
            if scope is not None and self._model_fallback_events(event):
                scope["ordinary_event"] = (
                    asyncio.current_task(),
                    event,
                    send_meta,
                )
            await self._ordinary_event_delivery(
                to_handle,
                send_meta,
                self._send_completed_event,
                request,
                to_handle,
                event,
                send_meta,
            )

    async def _ordinary_event_delivery(
        self,
        to_handle,
        send_meta,
        send,
        *args,
    ):
        identity = self._identity()
        try:
            policy = await self._response_policy(to_handle, send_meta)
        except _ResponseOpenDeliveryError as exc:
            if not exc.continue_on_delivery_error:
                raise
            self._require_enabled()
            if self._identity() != identity:
                raise _ChannelLifecycleError(
                    OutboundResult(
                        "unroutable",
                        DeliveryState.FAILED,
                        "STALE_GENERATION",
                    ),
                ) from exc
            health = self.channel_process.health_snapshot()
            if (
                not self._ingress_open
                or self._text_merge_stopping
                or health["state"] != "ready"
                or health["platform_state"] != "connected"
            ):
                raise _ChannelLifecycleError(
                    OutboundResult(
                        "unroutable",
                        DeliveryState.FAILED,
                        "CHANNEL_NOT_CONNECTED",
                    ),
                ) from exc
            self._record_continued_delivery_error(
                send_meta,
                ChannelDeliveryError(exc.result),
            )
            return
        try:
            return await send(*args)
        except ChannelDeliveryError as exc:
            if (
                isinstance(exc, _ChannelLifecycleError)
                or not policy.continue_on_delivery_error
            ):
                raise
            self._record_continued_delivery_error(send_meta, exc)

    def _record_continued_delivery_error(self, send_meta, exc):
        # Finish the Agent's event stream without claiming delivery.
        send_meta["_reply_failed"] = True
        send_meta.setdefault(
            "_continued_event_delivery_error",
            {"state": exc.state, "reason_code": exc.reason_code},
        )
        self._record_diagnostic(
            (
                "EVENT_DELIVERY_UNKNOWN"
                if exc.side_effect_possible
                else "EVENT_DELIVERY_FAILED"
            ),
        )

    async def _send_model_fallback_notice(self, to_handle, event, send_meta):
        scope = self._response_context.get()
        ordinary = scope.get("ordinary_event") if scope is not None else None
        if ordinary is None or not (
            ordinary[0] is asyncio.current_task()
            and ordinary[1] is event
            and ordinary[2] is send_meta
        ):
            return await super()._send_model_fallback_notice(
                to_handle,
                event,
                send_meta,
            )
        try:
            await self._ordinary_event_delivery(
                to_handle,
                send_meta,
                super()._send_model_fallback_notice,
                to_handle,
                event,
                send_meta,
            )
        finally:
            scope.pop("ordinary_event", None)

    async def _send_completed_event(
        self,
        request,
        to_handle,
        event,
        send_meta,
    ):
        if RAW_COMPLETED_TEXT_CAPABILITY in self.descriptor.capabilities:
            policy = await self._response_policy(to_handle, send_meta)
            parts, sources = project_completed_text(
                event,
                policy.raw_completed_text or "content",
            )
            if (
                parts
                or sources is not None
                and sources.error_source is not None
            ):
                fields = {"content_source": "event", "content_parts": parts}
                if sources is not None:
                    fields["raw_completed_text_sources"] = sources.to_mapping()
                await self._send_operation(
                    to_handle,
                    send_meta,
                    "message.create",
                    **fields,
                )
        elif SEMANTIC_PARTS_CAPABILITY in self.descriptor.capabilities:
            parts = []
            for item in self._renderer.message_to_semantic_parts(event):
                value = item.part.model_dump(mode="json", exclude_none=True)
                kind = value["type"]
                if kind in {"text", "refusal"}:
                    part = {"type": "text", "text": value[kind]}
                else:
                    locator = "data" if kind == "audio" else kind + "_url"
                    if item.role == "message" and not value.get(locator):
                        # A runtime-only reference has no transport locator.
                        # Rendered tool media still undergoes strict
                        # validation.
                        continue
                    part = {
                        key: value[key]
                        for key in (
                            "type",
                            locator,
                            "filename",
                            "mime_type",
                            "format",
                        )
                        if key in value
                    }
                parts.append(
                    {**validate_content_part(part), "role": item.role},
                )
            if parts:
                await self._send_operation(
                    to_handle,
                    send_meta,
                    "message.create",
                    content_source="event",
                    content_parts=parts,
                )
        else:
            await super().on_event_message_completed(
                request,
                to_handle,
                event,
                send_meta,
            )

    def _control_result(self, request, send_meta):
        from qwenpaw._control_state import ControlCommandState

        if not isinstance(request, AgentRequest):
            return None
        state = request._channel_control_state
        if (
            not isinstance(state, ControlCommandState)
            or not isinstance(state.resolution, ApprovalResolutionParams)
            or APPROVAL_RESOLUTION_CAPABILITY
            not in self.descriptor.capabilities
        ):
            return None
        binding = state.binding
        identity = self._identity()
        result = state.resolution
        if (
            binding.channel_key != identity.channel_key
            or binding.instance_id != identity.instance_id
            or binding.generation != identity.generation
            or binding.response_handle != send_meta.get("response_handle")
            or binding.session_id != request.session_id
            or binding.root_session_id != request.root_session_id
            or binding.user_id != request.user_id
            or result.actor_user_id != binding.user_id
            or binding.agent_id
            != (getattr(self._workspace, "agent_id", None) or "default")
            or (
                binding.source_request_id
                and binding.source_request_id != result.request_id
            )
        ):
            return None
        return state

    async def _send_control_resolution(
        self,
        request,
        to_handle,
        event,
        send_meta,
    ):
        state = self._control_result(request, send_meta)
        if state is None:
            return False
        result, state.resolution = state.resolution, None
        content = event.content or []
        body = (
            content
            if isinstance(content, str)
            else "".join(
                (
                    part.get("text", "")
                    if isinstance(part, dict)
                    else getattr(part, "text", "")
                )
                for part in content
            )
        )
        await self._send_operation(
            to_handle,
            send_meta,
            "message.create",
            approval_resolution=result.to_mapping(),
            content_parts=[{"type": "text", "text": body}] if body else [],
        )
        return True

    async def _dispatch_streaming_event(
        self,
        request,
        to_handle,
        event,
        send_meta,
        msg_id_to_stream_type,
        streaming_buffers,
    ):
        if self._control_result(request, send_meta) is not None:
            if event.object == "message" and event.status == "completed":
                return await self._send_control_resolution(
                    request,
                    to_handle,
                    event,
                    send_meta,
                )
            if event.object in {"message", "content"}:
                return True
        return await super()._dispatch_streaming_event(
            request,
            to_handle,
            event,
            send_meta,
            msg_id_to_stream_type,
            streaming_buffers,
        )

    async def _on_process_completed(self, request, to_handle, send_meta):
        self._require_enabled()
        await self._flush_response_text(send_meta.get("response_handle"))
        if send_meta.get("_continued_event_delivery_error"):
            # The Agent completed, but this response has failed delivery.
            # Its original unknown fence and failed finish outcome remain.
            return
        if send_meta.get("_reply_unknown"):
            raise ChannelDeliveryError(
                OutboundResult(
                    "unsettled",
                    DeliveryState.UNKNOWN,
                    "PLATFORM_RESULT_UNKNOWN",
                ),
            )
        if (
            not send_meta.get("_last_delivery_id")
            or not (
                await self._response_policy(to_handle, send_meta)
            ).completion_reaction
        ):
            return
        self._require_enabled()
        try:
            result = OutboundResult.from_mapping(
                await self.channel_process.call(
                    "channel.reaction",
                    {
                        **self._identity().to_mapping(),
                        "delivery_id": uuid.uuid4().hex,
                        "to_handle": send_meta["response_handle"],
                        "target_delivery_id": send_meta["_last_delivery_id"],
                        "reaction": "completed",
                    },
                ),
            )
            if result.state.value != "acknowledged":
                error = ChannelDeliveryError(result)
                if error.side_effect_possible:
                    send_meta["_reply_unknown"] = True
                raise error
        except (ChannelCallUnknown, asyncio.CancelledError):
            send_meta["_reply_unknown"] = True
            raise
        except RpcError as exc:
            if _rpc_result_unknown(exc):
                send_meta["_reply_unknown"] = True
            raise

    @asynccontextmanager
    async def _response_scope(self, meta):
        scope = {"meta": meta}
        token = self._response_context.set(scope)
        outcome = "completed"
        try:
            yield
            # Unlike best-effort route cleanup, a proactive flush is part of
            # the requested send and its failure must reach that caller.
            current = scope["meta"]
            await self._flush_response_text(current.get("response_handle"))
        except (asyncio.CancelledError, GeneratorExit):
            outcome = "cancelled"
            raise
        except BaseException:
            outcome = "failed"
            raise
        finally:
            current = scope["meta"]
            scope.pop("ordinary_event", None)
            merge_owned = (
                current.get("_text_merge_error") is not None
                or current.get("response_handle") in self._text_merge
                or any(
                    handle in self._text_merge
                    for handle in current.get("_merged_response_handles", ())
                )
            )
            if outcome == "completed" and (
                current.get("_reply_failed") or current.get("_reply_unknown")
            ):
                outcome = "failed"
            try:
                if current.get("response_handle"):
                    task = asyncio.create_task(
                        self._finish_route(current, outcome),
                    )
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError as cancelled:
                        if merge_owned:
                            # Merge cancellation owns this cleanup until it
                            # settles, including repeated owner cancellation.
                            while not task.done():
                                try:
                                    await asyncio.shield(task)
                                except asyncio.CancelledError:
                                    continue
                                except Exception:
                                    break  # Observe the exact result below.
                            try:
                                task.result()
                            except BaseException as cleanup_error:
                                self._record_diagnostic(
                                    "RESPONSE_FINISH_FAILED",
                                )
                                raise cancelled from cleanup_error
                        else:
                            task.add_done_callback(self._observe_cleanup)
                        raise
                    except Exception:
                        self._record_diagnostic("RESPONSE_FINISH_FAILED")
                        if merge_owned:
                            raise
            finally:
                self._response_context.reset(token)

    def _observe_cleanup(self, task):
        if task.cancelled() or task.exception() is not None:
            self._record_diagnostic("RESPONSE_FINISH_FAILED")

    async def _consume_request(self, request, payload):
        # Base calls this only after debounce and the host access gate.
        meta = getattr(request, "channel_meta", None) or {}
        request.channel_meta = meta
        async with self._response_scope(meta):
            await super()._consume_request(request, payload)

    async def _run_process_loop(self, request, to_handle, send_meta):
        # Preparation can add policy, delivery state or a newly opened route.
        send_meta.update(getattr(request, "channel_meta", None) or {})
        request.channel_meta = send_meta
        scope = self._response_context.get()
        if scope is not None:
            scope["meta"] = send_meta
            await super()._run_process_loop(request, to_handle, send_meta)
        else:
            async with self._response_scope(send_meta):
                await super()._run_process_loop(request, to_handle, send_meta)

    async def _stream_with_tracker(self, payload):
        meta = (
            dict(payload.get("meta") or {})
            if isinstance(payload, dict)
            else dict(getattr(payload, "channel_meta", None) or {})
        )
        async with self._response_scope(meta):
            iterator = super()._stream_with_tracker(payload)
            try:
                async for item in iterator:
                    yield item
            finally:
                await iterator.aclose()

# -*- coding: utf-8 -*-
"""Versioned JSON-RPC envelopes and Channel protocol DTOs."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping
from urllib.parse import urlsplit

from .descriptor import _http_url
from .errors import DescriptorValidationError, ProtocolValidationError
from ..plugins.execution.models import (  # pylint: disable=unused-import
    _error,
    _object,
    _closed,
    _string,
    _integer,
    _optional_string,
    _request_id,
    RpcErrorObject,
    RpcRequest,
    RpcNotification,
    RpcResponse,
    parse_rpc_message,
    CancelParams,
)
from .identifiers import validate_channel_key
from .management import ManagementRequest
from .completed_text import RawCompletedTextSources

JSONRPC_VERSION = "2.0"
CONTENT_SOURCE_CAPABILITY = "send.content_source.v1"
SEMANTIC_PARTS_CAPABILITY = "send.semantic_parts.v1"
RAW_COMPLETED_TEXT_CAPABILITY = "send.raw_completed_text.v1"
UNKNOWN_ACTOR_CAPABILITY = "event.unknown_actor.v1"
APPROVAL_RESOLUTION_CAPABILITY = "send.approval_resolution.v1"
TEXT_MERGE_CAPABILITY = "channel.text_merge.v1"
AUTH_QRCODE_CAPABILITY = "channel.auth.qrcode.v1"
MAX_METHOD_LENGTH = 128
MAX_RESPONSE_HANDLE_LENGTH = 512
MAX_AUTH_SCAN_URL_LENGTH = 4096


def send_source_capability(source, capabilities):
    """Raw completed text explicitly takes precedence over semantic output."""
    if source is ContentSource.EVENT:
        return (
            RAW_COMPLETED_TEXT_CAPABILITY
            if RAW_COMPLETED_TEXT_CAPABILITY in capabilities
            else SEMANTIC_PARTS_CAPABILITY
        )
    return CONTENT_SOURCE_CAPABILITY


def _required(
    value: Mapping[str, Any],
    name: str,
    *,
    path: tuple[str | int, ...] = (),
) -> Any:
    """Read a required field."""
    if name not in value:
        raise _error(
            f"missing required field: {name}",
            path=path + (name,),
            reason_code="SCHEMA_MISMATCH",
        )
    return value[name]


def validate_response_handle(value: object) -> str:
    """Validate one opaque request-scoped response handle."""
    handle = _string(value, "response_handle")
    if len(handle) > MAX_RESPONSE_HANDLE_LENGTH:
        raise _error(
            "response_handle exceeds the maximum length",
            path=("response_handle",),
        )
    if any(
        ord(character) < 32 or ord(character) == 127 for character in handle
    ):
        raise _error(
            "response_handle must not contain control characters",
            path=("response_handle",),
        )
    return handle


def _boolean(
    value: object,
    name: str,
    *,
    path: tuple[str | int, ...] = (),
) -> bool:
    """Require a JSON boolean."""
    if not isinstance(value, bool):
        raise _error(f"{name} must be a boolean", path=path + (name,))
    return value


def _list(
    value: object,
    name: str,
    *,
    path: tuple[str | int, ...] = (),
) -> list[Any]:
    """Require a JSON array."""
    if not isinstance(value, list):
        raise _error(f"{name} must be an array", path=path + (name,))
    return value


def _optional_integer(
    value: Mapping[str, Any],
    name: str,
    *,
    path: tuple[str | int, ...] = (),
    minimum: int | None = None,
) -> int | None:
    """Read an optional nullable integer."""
    if name not in value or value[name] is None:
        return None
    return _integer(value[name], name, path=path, minimum=minimum)


RpcMessage = RpcRequest | RpcResponse | RpcNotification


def _capabilities(value: object) -> tuple[str, ...]:
    """Validate a sorted, unique capability list."""
    values = _list(value, "capabilities")
    if any(not isinstance(item, str) or not item for item in values):
        raise _error("capabilities must contain non-empty strings")
    if len(set(values)) != len(values) or list(values) != sorted(values):
        raise _error("capabilities must be sorted and unique")
    return tuple(values)


@dataclass(frozen=True)
class IdentityParams:
    """Common instance and generation identity for control methods."""

    channel_key: str
    instance_id: str
    generation: int

    def to_mapping(self) -> dict[str, Any]:
        """Encode control identity."""
        return {
            "channel_key": self.channel_key,
            "instance_id": self.instance_id,
            "generation": self.generation,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "IdentityParams":
        """Validate control identity."""
        data = _object(value)
        _closed(data, {"channel_key", "instance_id", "generation"})
        return cls(
            channel_key=validate_channel_key(
                _string(data.get("channel_key"), "channel_key"),
            ),
            instance_id=_string(data.get("instance_id"), "instance_id"),
            generation=_integer(
                data.get("generation"),
                "generation",
                minimum=1,
            ),
        )


_IDENTITY_FIELDS = ("channel_key", "instance_id", "generation")


def _identity_from_fields(data: Mapping[str, Any]) -> IdentityParams:
    """Validate the identity subset of a containing DTO."""
    return IdentityParams.from_mapping(
        {name: data[name] for name in _IDENTITY_FIELDS},
    )


@dataclass(frozen=True)
class AuthRequiredParams(IdentityParams):
    """One current worker's terminal QR login prompt."""

    scan_url: str

    @classmethod
    def from_mapping(cls, value: object) -> "AuthRequiredParams":
        data = _object(value)
        _closed(data, {*_IDENTITY_FIELDS, "scan_url"})
        identity = _identity_from_fields(data)
        scan_url = _string(data.get("scan_url"), "scan_url")
        if len(scan_url) > MAX_AUTH_SCAN_URL_LENGTH or any(
            0x7F <= ord(character) < 0xA0 for character in scan_url
        ):
            raise _error("Invalid QR scan URL", path=("scan_url",))
        try:
            _http_url(scan_url, "scan_url")
        except DescriptorValidationError as exc:
            raise _error("Invalid QR scan URL", path=("scan_url",)) from exc
        parts = urlsplit(scan_url)
        if parts.username is not None:
            raise _error("Invalid QR scan URL", path=("scan_url",))
        host = parts.hostname or ""
        try:
            ipaddress.ip_address(host)
        except ValueError:
            try:
                host = host.encode("idna").decode("ascii").removesuffix(".")
            except UnicodeError as exc:
                raise _error(
                    "Invalid QR scan URL",
                    path=("scan_url",),
                ) from exc
            if len(host) > 253 or any(
                re.fullmatch(
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
                    label,
                )
                is None
                for label in host.split(".")
            ):
                raise _error("Invalid QR scan URL", path=("scan_url",))
        return cls(**identity.__dict__, scan_url=scan_url)

    def to_mapping(self) -> dict[str, Any]:
        return {**super().to_mapping(), "scan_url": self.scan_url}


class ResponsePrepareKind(StrEnum):
    """Internal reply preparation intent, independent of streaming."""

    PREPARE = "response.prepare"


@dataclass(frozen=True)
class ResponsePrepareOperation(IdentityParams):
    """Validated internal preparation operation for the delivery journal."""

    delivery_id: str
    to_handle: str
    operation: ResponsePrepareKind = ResponsePrepareKind.PREPARE

    def to_mapping(self) -> dict[str, Any]:
        return {
            **super().to_mapping(),
            "delivery_id": self.delivery_id,
            "to_handle": self.to_handle,
            "operation": self.operation.value,
        }


@dataclass(frozen=True)
class EndpointParams(IdentityParams):
    """Runner-owned ingress endpoint registration DTO."""

    protocol: str
    host: str
    port: int
    path: str
    public_base_url: str | None
    readiness: str
    bound_externally: bool
    auth_required: bool
    quiescing: bool = False

    @classmethod
    def from_mapping(cls, value: object) -> "EndpointParams":
        """Validate an endpoint registration/update DTO."""
        data = _object(value)
        allowed = {
            *_IDENTITY_FIELDS,
            "protocol",
            "host",
            "port",
            "path",
            "public_base_url",
            "readiness",
            "bound_externally",
            "auth_required",
            "quiescing",
        }
        _closed(data, allowed)
        identity = _identity_from_fields(data)
        protocol = _string(data.get("protocol"), "protocol")
        host = _string(data.get("host"), "host")
        port = _integer(data.get("port"), "port", minimum=0)
        path = _string(data.get("path"), "path")
        if not path.startswith("/"):
            raise _error("path must start with '/'", path=("path",))
        readiness = _string(data.get("readiness"), "readiness")
        if readiness not in {"starting", "ready", "degraded", "stopped"}:
            raise _error("invalid endpoint readiness", path=("readiness",))
        _boolean(
            data.get("bound_externally"),
            "bound_externally",
        )
        auth_required = _boolean(data.get("auth_required"), "auth_required")
        bound_externally = is_external_host(host)
        if bound_externally and not auth_required:
            raise _error(
                "externally bound endpoint must require authentication",
                reason_code="AUTH_FAILED",
            )
        return cls(
            **identity.__dict__,
            protocol=protocol,
            host=host,
            port=port,
            path=path,
            public_base_url=_optional_string(data, "public_base_url"),
            readiness=readiness,
            bound_externally=bound_externally,
            auth_required=auth_required,
            quiescing=_boolean(data.get("quiescing", False), "quiescing"),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode endpoint DTO."""
        return {
            **super().to_mapping(),
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "path": self.path,
            "public_base_url": self.public_base_url,
            "readiness": self.readiness,
            "bound_externally": self.bound_externally,
            "auth_required": self.auth_required,
            "quiescing": self.quiescing,
        }


@dataclass(frozen=True)
class HostForwardingBinding:
    """Host-authorized routes and a generation-private ingress credential."""

    route_query_key: str
    route_selector: str
    host_port: int
    paths: tuple[str, ...]
    bridge_token: str = field(repr=False)

    @classmethod
    def from_mapping(cls, value: object) -> "HostForwardingBinding":
        data = _object(value)
        _closed(
            data,
            {
                "route_query_key",
                "route_selector",
                "host_port",
                "paths",
                "bridge_token",
            },
        )
        key = _string(data.get("route_query_key"), "route_query_key")
        if key != "_qp_endpoint":
            raise _error("invalid route query key")
        selector = _string(data.get("route_selector"), "route_selector")
        port = _integer(data.get("host_port"), "host_port", minimum=1)
        if port > 65535:
            raise _error("invalid host port")
        paths = data.get("paths")
        if not isinstance(paths, list) or not paths:
            raise _error("paths must be a nonempty array")
        paths = tuple(_string(path, "paths") for path in paths)
        if len(set(paths)) != len(paths) or any(
            not path.startswith("/")
            or path.startswith("//")
            or any(c in path for c in "?#\\")
            or ".." in path
            or any(ord(c) < 33 for c in path)
            for path in paths
        ):
            raise _error("invalid forwarding path")
        return cls(
            key,
            selector,
            port,
            paths,
            _string(data.get("bridge_token"), "bridge_token"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "route_query_key": self.route_query_key,
            "route_selector": self.route_selector,
            "host_port": self.host_port,
            "paths": list(self.paths),
            "bridge_token": self.bridge_token,
        }


@dataclass(frozen=True)
class EndpointRegistrationResult:
    """Compatible endpoint ACK with optional host-owned forwarding."""

    status: str
    generation: int
    readiness: str
    forwarding: HostForwardingBinding | None = None

    @classmethod
    def from_mapping(cls, value: object) -> "EndpointRegistrationResult":
        data = _object(value)
        _closed(data, {"status", "generation", "readiness", "forwarding"})
        status = _string(data.get("status"), "status")
        readiness = _string(data.get("readiness"), "readiness")
        if status not in {"registered", "updated"} or readiness not in {
            "starting",
            "ready",
            "degraded",
            "stopped",
        }:
            raise _error("invalid endpoint registration result")
        forwarding = data.get("forwarding")
        return cls(
            status,
            _integer(data.get("generation"), "generation", minimum=1),
            readiness,
            (
                HostForwardingBinding.from_mapping(forwarding)
                if forwarding is not None
                else None
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        result = {
            "status": self.status,
            "generation": self.generation,
            "readiness": self.readiness,
        }
        if self.forwarding is not None:
            result["forwarding"] = self.forwarding.to_mapping()
        return result


def is_external_host(host: str) -> bool:
    """Return whether an endpoint host is exposed beyond loopback."""
    normalized = host.strip().lower()
    if normalized == "localhost":
        return False
    try:
        return not ipaddress.ip_address(normalized.strip("[]")).is_loopback
    except ValueError:
        return True


def validate_content_part(value: object) -> dict[str, Any]:
    """Validate one platform-independent Content locator."""
    data = _object(value)
    content_type = _string(data.get("type"), "type")
    fields = {
        "text": {"type", "text"},
        "image": {"type", "image_url", "filename", "mime_type"},
        "video": {"type", "video_url", "filename", "mime_type"},
        "file": {"type", "file_url", "filename", "mime_type"},
        "audio": {"type", "data", "format", "filename", "mime_type"},
    }
    if content_type not in fields:
        raise _error("unsupported content type", path=("type",))
    _closed(data, fields[content_type])
    if content_type == "text":
        _string(data.get("text"), "text", non_empty=False)
    else:
        locator_name = (
            "data" if content_type == "audio" else f"{content_type}_url"
        )
        _string(data.get(locator_name), locator_name)
        for name in ("filename", "mime_type", "format"):
            if name in data and data[name] is not None:
                _string(data[name], name)
    return data


def _conversation(value: object) -> dict[str, Any]:
    """Validate the stable conversation identity carried by an event."""
    data = _object(value, path=("conversation",))
    _closed(
        data,
        {"id", "type", "thread_id"},
        path=("conversation",),
    )
    result = {
        "id": _string(data.get("id"), "id", path=("conversation",)),
        "type": _string(
            data.get("type"),
            "type",
            path=("conversation",),
        ),
        "thread_id": _optional_string(
            data,
            "thread_id",
            path=("conversation",),
        ),
    }
    return result


@dataclass(frozen=True)
class InboundEvent:
    """Stable platform-independent event submitted by a Runner."""

    event_id: str
    channel_key: str
    instance_id: str
    generation: int
    conversation: Mapping[str, Any]
    sender_id: str
    acl_sender_id: str
    sender_name: str
    content_parts: tuple[dict[str, Any], ...]
    event_kind: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    response_handle: str | None = None
    actor_unknown: bool = False

    @classmethod
    def from_mapping(cls, value: object) -> "InboundEvent":
        """Validate one stable inbound event."""
        data = _object(value)
        _closed(
            data,
            {
                "event_id",
                "event_kind",
                *_IDENTITY_FIELDS,
                "conversation",
                "sender_id",
                "acl_sender_id",
                "sender_name",
                "content_parts",
                "metadata",
                "response_handle",
                "actor_unknown",
            },
        )
        content_parts = _list(data.get("content_parts"), "content_parts")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise _error("metadata must be an object", path=("metadata",))
        event_kind = _string(data.get("event_kind"), "event_kind")
        unknown = _boolean(data.get("actor_unknown", False), "actor_unknown")
        sender = _string(
            data.get("sender_id"),
            "sender_id",
            non_empty=not unknown,
        )
        acl_sender = _string(
            data.get("acl_sender_id"),
            "acl_sender_id",
            non_empty=not unknown,
        )
        if unknown and (
            sender != ""
            or acl_sender != ""
            or metadata.get("user_id") != ""
            or event_kind not in {"message", "message.query"}
        ):
            raise _error(
                "Unknown actor requires an anonymous ordinary message",
            )
        return cls(
            event_id=_string(data.get("event_id"), "event_id"),
            event_kind=event_kind,
            channel_key=validate_channel_key(
                _string(data.get("channel_key"), "channel_key"),
            ),
            instance_id=_string(data.get("instance_id"), "instance_id"),
            generation=_integer(
                data.get("generation"),
                "generation",
                minimum=1,
            ),
            conversation=_conversation(data.get("conversation")),
            sender_id=sender,
            acl_sender_id=acl_sender,
            actor_unknown=unknown,
            sender_name=_string(
                data.get("sender_name"),
                "sender_name",
                non_empty=False,
            ),
            content_parts=tuple(
                validate_content_part(item) for item in content_parts
            ),
            metadata=dict(metadata),
            response_handle=(
                validate_response_handle(data["response_handle"])
                if "response_handle" in data
                and data["response_handle"] is not None
                else None
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode one stable inbound event."""
        result = {
            "event_id": self.event_id,
            "channel_key": self.channel_key,
            "instance_id": self.instance_id,
            "generation": self.generation,
            "conversation": dict(self.conversation),
            "sender_id": self.sender_id,
            "acl_sender_id": self.acl_sender_id,
            "sender_name": self.sender_name,
            "content_parts": list(self.content_parts),
            "metadata": dict(self.metadata),
        }
        result["event_kind"] = self.event_kind
        if self.response_handle is not None:
            result["response_handle"] = self.response_handle
        if self.actor_unknown:
            result["actor_unknown"] = True
        return result


@dataclass(frozen=True)
class EventBatchParams:
    """Reliable batch of inbound events submitted by a Runner."""

    batch_id: str
    events: tuple[InboundEvent, ...]
    invalid_events: tuple[RejectedEvent, ...] = ()
    identity: IdentityParams | None = None

    @classmethod
    def from_mapping(cls, value: object) -> "EventBatchParams":
        """Validate a non-empty event batch and its shared identity."""
        data = _object(value)
        _closed(data, {"batch_id", "events"})
        raw_events = _list(data.get("events"), "events")
        if not raw_events:
            raise _error("events must not be empty", path=("events",))
        events: list[InboundEvent] = []
        invalid_events: list[RejectedEvent] = []
        identity: IdentityParams | None = None
        seen_event_ids: set[str] = set()
        for item in raw_events:
            raw_item = item if isinstance(item, Mapping) else {}
            item_identity = IdentityParams.from_mapping(
                {key: raw_item.get(key) for key in _IDENTITY_FIELDS},
            )
            if identity is None:
                identity = item_identity
            elif item_identity != identity:
                raise _error(
                    "all events in a batch must share identity",
                    reason_code="SCHEMA_MISMATCH",
                )
            try:
                event = InboundEvent.from_mapping(item)
                if event.event_id in seen_event_ids:
                    raise _error(
                        "event_id must be unique within a batch",
                        path=("event_id",),
                        reason_code="SCHEMA_MISMATCH",
                    )
                events.append(event)
                seen_event_ids.add(event.event_id)
            except ProtocolValidationError as exc:
                event_id = raw_item.get("event_id")
                if not isinstance(event_id, str) or not event_id:
                    raise
                if event_id in seen_event_ids:
                    raise _error(
                        "event_id must be unique within a batch",
                        path=("event_id",),
                        reason_code="SCHEMA_MISMATCH",
                    ) from exc
                invalid_events.append(
                    RejectedEvent(
                        event_id=event_id,
                        reason_code=exc.reason_code,
                        retryable=False,
                    ),
                )
                seen_event_ids.add(event_id)
        event_tuple = tuple(events)
        return cls(
            batch_id=_string(data.get("batch_id"), "batch_id"),
            events=event_tuple,
            invalid_events=tuple(invalid_events),
            identity=identity,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode a reliable event batch."""
        return {
            "batch_id": self.batch_id,
            "events": [event.to_mapping() for event in self.events],
        }


@dataclass(frozen=True)
class RejectedEvent:
    """Per-event rejection returned in a reliable batch ACK."""

    event_id: str
    reason_code: str
    retryable: bool

    @classmethod
    def from_mapping(cls, value: object) -> "RejectedEvent":
        """Validate a rejected event result."""
        data = _object(value)
        _closed(data, {"event_id", "reason_code", "retryable"})
        return cls(
            event_id=_string(data.get("event_id"), "event_id"),
            reason_code=_string(data.get("reason_code"), "reason_code"),
            retryable=_boolean(data.get("retryable"), "retryable"),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode a rejected event result."""
        return {
            "event_id": self.event_id,
            "reason_code": self.reason_code,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class EventBatchAck:
    """Per-event ACK returned after Core persistence and deduplication."""

    accepted_event_ids: tuple[str, ...] = ()
    duplicate_event_ids: tuple[str, ...] = ()
    rejected_events: tuple[RejectedEvent, ...] = ()
    batch_id: str | None = None

    @classmethod
    def from_mapping(cls, value: object) -> "EventBatchAck":
        """Validate an event batch ACK."""
        data = _object(value)
        _closed(
            data,
            {
                "batch_id",
                "accepted_event_ids",
                "duplicate_event_ids",
                "rejected_events",
            },
        )
        accepted = _list(
            data.get("accepted_event_ids", []),
            "accepted_event_ids",
        )
        duplicates = _list(
            data.get("duplicate_event_ids", []),
            "duplicate_event_ids",
        )
        if any(not isinstance(item, str) or not item for item in accepted):
            raise _error(
                "accepted_event_ids must contain non-empty strings",
                path=("accepted_event_ids",),
            )
        if any(not isinstance(item, str) or not item for item in duplicates):
            raise _error(
                "duplicate_event_ids must contain non-empty strings",
                path=("duplicate_event_ids",),
            )
        if set(accepted).intersection(duplicates):
            raise _error(
                "accepted and duplicate event IDs must be disjoint",
                reason_code="SCHEMA_MISMATCH",
            )
        rejected = _list(data.get("rejected_events", []), "rejected_events")
        rejected_ids = [
            item.get("event_id")
            for item in rejected
            if isinstance(item, Mapping)
        ]
        if set(accepted).intersection(rejected_ids) or set(
            duplicates,
        ).intersection(
            rejected_ids,
        ):
            raise _error(
                "ACK event classifications must be disjoint",
                reason_code="SCHEMA_MISMATCH",
            )
        return cls(
            batch_id=_optional_string(data, "batch_id"),
            accepted_event_ids=tuple(accepted),
            duplicate_event_ids=tuple(duplicates),
            rejected_events=tuple(
                RejectedEvent.from_mapping(item) for item in rejected
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode an event batch ACK."""
        result = {
            "accepted_event_ids": list(self.accepted_event_ids),
            "duplicate_event_ids": list(self.duplicate_event_ids),
            "rejected_events": [
                item.to_mapping() for item in self.rejected_events
            ],
        }
        if self.batch_id is not None:
            result["batch_id"] = self.batch_id
        return result


class DeliveryState(StrEnum):
    """Stable outbound delivery ledger states."""

    REQUESTED = "requested"
    SENDING = "sending"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


_OUTBOUND_RESULT_STATES = {
    DeliveryState.ACKNOWLEDGED,
    DeliveryState.FAILED,
    DeliveryState.TIMEOUT,
    DeliveryState.UNKNOWN,
}


@dataclass(frozen=True)
class OutboundResult:
    """Closed result DTO for one platform-side outbound attempt."""

    delivery_id: str
    state: DeliveryState
    reason_code: str | None = None
    retryable: bool = False

    @classmethod
    def from_mapping(cls, value: object) -> "OutboundResult":
        """Validate one terminal outbound result."""
        data = _object(value)
        _closed(
            data,
            {"delivery_id", "state", "reason_code", "retryable"},
        )
        state_value = _string(data.get("state"), "state")
        try:
            state = DeliveryState(state_value)
        except ValueError as exc:
            raise _error(
                "unsupported outbound result state",
                path=("state",),
            ) from exc
        if state not in _OUTBOUND_RESULT_STATES:
            raise _error(
                "outbound result state must be terminal",
                path=("state",),
            )
        return cls(
            delivery_id=_string(data.get("delivery_id"), "delivery_id"),
            state=state,
            reason_code=_optional_string(data, "reason_code"),
            retryable=_boolean(data.get("retryable", False), "retryable"),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode one terminal outbound result."""
        result: dict[str, Any] = {
            "delivery_id": self.delivery_id,
            "state": self.state.value,
            "retryable": self.retryable,
        }
        if self.reason_code is not None:
            result["reason_code"] = self.reason_code
        return result


@dataclass(frozen=True)
class DeliveryUpdateParams(IdentityParams):
    """Runner result update for an immutable outbound delivery."""

    delivery_id: str
    state: DeliveryState
    reason_code: str | None = None
    retryable: bool = False

    @classmethod
    def from_mapping(cls, value: object) -> "DeliveryUpdateParams":
        """Validate a delivery ledger update."""
        data = _object(value)
        _closed(
            data,
            {
                *_IDENTITY_FIELDS,
                "delivery_id",
                "state",
                "reason_code",
                "retryable",
            },
        )
        identity = _identity_from_fields(data)
        state_value = _string(data.get("state"), "state")
        try:
            state = DeliveryState(state_value)
        except ValueError as exc:
            raise _error(
                "unsupported delivery state",
                path=("state",),
            ) from exc
        if state is DeliveryState.REQUESTED:
            raise _error(
                "delivery update state must be sending or terminal",
                path=("state",),
            )
        return cls(
            **identity.__dict__,
            delivery_id=_string(data.get("delivery_id"), "delivery_id"),
            state=state,
            reason_code=_optional_string(data, "reason_code"),
            retryable=_boolean(data.get("retryable", False), "retryable"),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode a delivery ledger update."""
        result = {
            **super().to_mapping(),
            "delivery_id": self.delivery_id,
            "state": self.state.value,
            "retryable": self.retryable,
        }
        if self.reason_code is not None:
            result["reason_code"] = self.reason_code
        return result


class OutboundOperation(StrEnum):
    """Platform-independent outbound operations carried by channel.send."""

    MESSAGE_CREATE = "message.create"
    MESSAGE_UPDATE = "message.update"
    STREAM_START = "stream.start"
    STREAM_DELTA = "stream.delta"
    STREAM_END = "stream.end"


class StreamType(StrEnum):
    """Stable stream categories produced by Core event aggregation."""

    REASONING = "reasoning"
    MESSAGE = "message"


class ApprovalSeverity(StrEnum):
    """Stable tool-approval severity values."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ApprovalCardParams:
    """Platform-independent tool approval card semantics."""

    request_id: str
    tool_name: str
    severity: ApprovalSeverity

    @classmethod
    def from_mapping(cls, value: object) -> "ApprovalCardParams":
        """Validate a closed approval card object."""
        data = _object(value, path=("approval",))
        _closed(
            data,
            {"request_id", "tool_name", "severity"},
            path=("approval",),
        )
        severity_value = _string(
            data.get("severity"),
            "severity",
            path=("approval",),
        )
        try:
            severity = ApprovalSeverity(severity_value)
        except ValueError as exc:
            raise _error(
                "unsupported approval severity",
                path=("approval", "severity"),
            ) from exc
        return cls(
            request_id=_string(
                data.get("request_id"),
                "request_id",
                path=("approval",),
            ),
            tool_name=_string(
                data.get("tool_name"),
                "tool_name",
                path=("approval",),
            ),
            severity=severity,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode platform-independent approval semantics."""
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "severity": self.severity.value,
        }


class ContentSource(StrEnum):
    """Opt-in presentation origins for existing public send methods."""

    DIRECT = "direct"
    CONTENT_PARTS = "content_parts"
    MEDIA = "media"
    EVENT = "event"


def _validate_event_part(value: object) -> dict[str, Any]:
    """Allow neutral roles only on outbound completed-event content."""
    data = dict(_object(value))
    if "role" not in data:
        return validate_content_part(data)
    role = _string(data.pop("role"), "role")
    if role not in {"message", "reasoning", "refusal", "rendered"}:
        raise _error("unsupported content role", path=("role",))
    part = validate_content_part(data)
    if role in {"reasoning", "refusal"} and part["type"] != "text":
        raise _error("content role requires text", path=("role",))
    return {**part, "role": role}


class ApprovalResolutionOutcome(StrEnum):
    """Authoritative command outcomes; admission is never a decision."""

    APPROVED = "approved"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"
    FORBIDDEN = "forbidden"
    FAILED = "failed"


@dataclass(frozen=True)
class ApprovalResolutionParams:
    """Bounded display semantics from an actual host approval command."""

    request_id: str
    outcome: ApprovalResolutionOutcome
    actor_user_id: str
    tool_name: str | None = None

    def __post_init__(self):
        try:
            object.__setattr__(
                self,
                "outcome",
                ApprovalResolutionOutcome(self.outcome),
            )
        except (ValueError, TypeError) as exc:
            raise _error("unsupported approval outcome") from exc
        for name, maximum in (
            ("request_id", 256),
            ("actor_user_id", 512),
            ("tool_name", 1024),
        ):
            value = getattr(self, name)
            if name == "tool_name" and value is None:
                continue
            _string(value, name, path=("approval_resolution",))
            if len(value.encode("utf-8")) > maximum:
                raise _error("approval result field too large", path=(name,))
        success = self.outcome in {
            ApprovalResolutionOutcome.APPROVED,
            ApprovalResolutionOutcome.DENIED,
        }
        if success != (self.tool_name is not None):
            raise _error("approval tool name requires a successful result")
        if len(json.dumps(self.to_mapping()).encode("utf-8")) > 16384:
            raise _error("approval result too large")

    @classmethod
    def from_mapping(cls, value):
        data = _object(value, path=("approval_resolution",))
        _closed(
            data,
            {"request_id", "outcome", "actor_user_id", "tool_name"},
            path=("approval_resolution",),
        )
        return cls(
            request_id=data.get("request_id"),
            outcome=data.get("outcome"),
            actor_user_id=data.get("actor_user_id"),
            tool_name=data.get("tool_name"),
        )

    def to_mapping(self):
        result = {
            "request_id": self.request_id,
            "outcome": self.outcome.value,
            "actor_user_id": self.actor_user_id,
        }
        if self.tool_name is not None:
            result["tool_name"] = self.tool_name
        return result


def _reject_operation_fields(
    data: Mapping[str, Any],
    names: tuple[str, ...],
    operation: OutboundOperation,
) -> None:
    """Reject fields that are not valid for one outbound operation."""
    for name in names:
        if name in data:
            raise _error(
                f"{name} is not valid for {operation.value}",
                path=(name,),
                reason_code="SCHEMA_MISMATCH",
            )


def _require_send_parts(parts: tuple[dict[str, Any], ...]) -> None:
    """Require one outbound operation to carry content parts."""
    if not parts:
        raise _error(
            "content_parts must not be empty",
            path=("content_parts",),
        )


def _require_send_target(target_delivery_id: str | None) -> None:
    """Require one outbound operation to reference an existing target."""
    if target_delivery_id is None:
        raise _error(
            "target_delivery_id is required",
            path=("target_delivery_id",),
        )


def _require_send_sequence(sequence: int | None) -> None:
    """Require a positive sequence for one outbound update."""
    if sequence is None or sequence < 1:
        raise _error(
            "sequence must be at least 1",
            path=("sequence",),
        )


def _require_send_stream(
    stream_type: StreamType | None,
    accumulated_text: str | None,
) -> None:
    """Require stable stream identity and accumulated text."""
    if stream_type is None:
        raise _error(
            "stream_type is required",
            path=("stream_type",),
        )
    if accumulated_text is None:
        raise _error(
            "accumulated_text is required",
            path=("accumulated_text",),
        )


def _parse_outbound_operation(data: Mapping[str, Any]) -> OutboundOperation:
    """Parse the operation with message.create as the v1 default."""
    value = data.get("operation", OutboundOperation.MESSAGE_CREATE.value)
    try:
        return OutboundOperation(_string(value, "operation"))
    except ValueError as exc:
        raise _error(
            "unsupported outbound operation",
            path=("operation",),
        ) from exc


def _parse_stream_type(data: Mapping[str, Any]) -> StreamType | None:
    """Parse an optional stable stream type."""
    if "stream_type" not in data or data["stream_type"] is None:
        return None
    value = _string(data["stream_type"], "stream_type")
    try:
        return StreamType(value)
    except ValueError as exc:
        raise _error(
            "unsupported stream type",
            path=("stream_type",),
        ) from exc


def _validate_send_fields(
    data: Mapping[str, Any],
    operation: OutboundOperation,
    parts: tuple[dict[str, Any], ...],
    target_delivery_id: str | None,
    stream_type: StreamType | None,
    sequence: int | None,
    accumulated_text: str | None,
) -> None:
    """Validate the field combination for one outbound operation."""
    if operation is OutboundOperation.MESSAGE_CREATE:
        if (
            data.get("approval_resolution") is None
            and data.get("raw_completed_text_sources") is None
        ):
            _require_send_parts(parts)
        _reject_operation_fields(
            data,
            (
                "target_delivery_id",
                "stream_type",
                "sequence",
                "accumulated_text",
            ),
            operation,
        )
        return
    if operation is OutboundOperation.MESSAGE_UPDATE:
        _require_send_sequence(sequence)
        _require_send_parts(parts)
        _require_send_target(target_delivery_id)
        _reject_operation_fields(
            data,
            ("stream_type", "accumulated_text", "approval"),
            operation,
        )
        return
    _require_send_stream(stream_type, accumulated_text)
    if operation is OutboundOperation.STREAM_START:
        if sequence != 0:
            raise _error(
                "stream.start sequence must be 0",
                path=("sequence",),
            )
        _reject_operation_fields(
            data,
            ("content_parts", "target_delivery_id", "approval"),
            operation,
        )
        return
    _require_send_sequence(sequence)
    _require_send_target(target_delivery_id)
    _reject_operation_fields(
        data,
        ("content_parts", "approval"),
        operation,
    )


@dataclass(frozen=True)
class SendParams(IdentityParams):
    """Platform-independent outbound operation DTO."""

    delivery_id: str
    to_handle: str
    operation: OutboundOperation
    content_parts: tuple[dict[str, Any], ...] = ()
    target_delivery_id: str | None = None
    stream_type: StreamType | None = None
    sequence: int | None = None
    accumulated_text: str | None = None
    approval: ApprovalCardParams | None = None
    content_source: ContentSource | None = None
    approval_resolution: ApprovalResolutionParams | None = None
    raw_completed_text_sources: RawCompletedTextSources | None = None

    @classmethod
    def from_mapping(cls, value: object) -> "SendParams":
        """Validate outbound content and delivery identity."""
        data = _object(value)
        _closed(
            data,
            {
                *_IDENTITY_FIELDS,
                "delivery_id",
                "to_handle",
                "operation",
                "content_parts",
                "target_delivery_id",
                "stream_type",
                "sequence",
                "accumulated_text",
                "approval",
                "content_source",
                "approval_resolution",
                "raw_completed_text_sources",
            },
        )
        identity = _identity_from_fields(data)
        operation = _parse_outbound_operation(data)
        source = None
        if data.get("content_source") is not None:
            try:
                source = ContentSource(data["content_source"])
            except (ValueError, TypeError) as exc:
                raise _error("unsupported content source") from exc
        raw_parts = _list(data.get("content_parts", []), "content_parts")
        validate_part = (
            _validate_event_part
            if source is ContentSource.EVENT
            else validate_content_part
        )
        parts = tuple(validate_part(item) for item in raw_parts)
        target_delivery_id = _optional_string(data, "target_delivery_id")
        sequence = _optional_integer(data, "sequence", minimum=0)
        accumulated_text = _optional_string(
            data,
            "accumulated_text",
            non_empty=False,
        )
        stream_type = _parse_stream_type(data)
        approval = None
        if "approval" in data and data["approval"] is not None:
            approval = ApprovalCardParams.from_mapping(data["approval"])
        resolution = None
        if data.get("approval_resolution") is not None:
            resolution = ApprovalResolutionParams.from_mapping(
                data["approval_resolution"],
            )
        raw_sources = None
        if data.get("raw_completed_text_sources") is not None:
            raw_sources = RawCompletedTextSources.from_mapping(
                data["raw_completed_text_sources"],
            )
            if (
                source is not ContentSource.EVENT
                or operation is not OutboundOperation.MESSAGE_CREATE
                or approval is not None
                or resolution is not None
                or any(part["type"] != "text" for part in parts)
            ):
                raise _error(
                    "Raw text sources require an ordinary completed text event",
                )
            if not parts and raw_sources.error_source is None:
                _require_send_parts(parts)
        if operation is not OutboundOperation.MESSAGE_CREATE and (
            source is not None or resolution is not None
        ):
            raise _error("presentation fields require message.create")
        if approval is not None and resolution is not None:
            raise _error("approval and resolution are mutually exclusive")
        if source is ContentSource.MEDIA and (
            len(parts) != 1
            or parts[0]["type"] == "text"
            or approval is not None
            or resolution is not None
        ):
            raise _error("media source requires exactly one media part")
        _validate_send_fields(
            data,
            operation,
            parts,
            target_delivery_id,
            stream_type,
            sequence,
            accumulated_text,
        )
        return cls(
            **identity.__dict__,
            delivery_id=_string(data.get("delivery_id"), "delivery_id"),
            to_handle=_string(data.get("to_handle"), "to_handle"),
            operation=operation,
            content_parts=parts,
            target_delivery_id=target_delivery_id,
            stream_type=stream_type,
            sequence=sequence,
            accumulated_text=accumulated_text,
            approval=approval,
            content_source=source,
            approval_resolution=resolution,
            raw_completed_text_sources=raw_sources,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode outbound message DTO."""
        result: dict[str, Any] = {
            **super().to_mapping(),
            "delivery_id": self.delivery_id,
            "to_handle": self.to_handle,
            "operation": self.operation.value,
        }
        if self.content_parts:
            result["content_parts"] = [
                dict(part) for part in self.content_parts
            ]
        if self.target_delivery_id is not None:
            result["target_delivery_id"] = self.target_delivery_id
        if self.stream_type is not None:
            result["stream_type"] = self.stream_type.value
        if self.sequence is not None:
            result["sequence"] = self.sequence
        if self.accumulated_text is not None:
            result["accumulated_text"] = self.accumulated_text
        if self.approval is not None:
            result["approval"] = self.approval.to_mapping()
        if self.content_source is not None:
            result["content_source"] = self.content_source.value
        if self.approval_resolution is not None:
            result[
                "approval_resolution"
            ] = self.approval_resolution.to_mapping()
        if self.raw_completed_text_sources is not None:
            result[
                "raw_completed_text_sources"
            ] = self.raw_completed_text_sources.to_mapping()
        return result


@dataclass(frozen=True)
class ReactionParams(IdentityParams):
    """Platform-independent reaction operation DTO."""

    delivery_id: str
    to_handle: str
    target_delivery_id: str
    reaction: str

    @classmethod
    def from_mapping(cls, value: object) -> "ReactionParams":
        """Validate the v1 completed reaction operation."""
        data = _object(value)
        _closed(
            data,
            {
                *_IDENTITY_FIELDS,
                "delivery_id",
                "to_handle",
                "target_delivery_id",
                "reaction",
            },
        )
        identity = _identity_from_fields(data)
        reaction = _string(data.get("reaction"), "reaction")
        if reaction != "completed":
            raise _error(
                "unsupported reaction",
                path=("reaction",),
            )
        return cls(
            **identity.__dict__,
            delivery_id=_string(data.get("delivery_id"), "delivery_id"),
            to_handle=_string(data.get("to_handle"), "to_handle"),
            target_delivery_id=_string(
                data.get("target_delivery_id"),
                "target_delivery_id",
            ),
            reaction=reaction,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode a platform-independent reaction operation."""
        return {
            **super().to_mapping(),
            "delivery_id": self.delivery_id,
            "to_handle": self.to_handle,
            "target_delivery_id": self.target_delivery_id,
            "reaction": self.reaction,
        }


class ResponseOutcome(StrEnum):
    """Stable terminal outcomes for one request-scoped response."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ResponseFinishParams(IdentityParams):
    """Close one opaque request-scoped response lifecycle."""

    response_handle: str
    outcome: ResponseOutcome

    @classmethod
    def from_mapping(cls, value: object) -> "ResponseFinishParams":
        """Validate a response finalization request."""
        data = _object(value)
        _closed(
            data,
            {
                *_IDENTITY_FIELDS,
                "response_handle",
                "outcome",
            },
        )
        identity = IdentityParams.from_mapping(
            {
                key: _required(data, key)
                for key in ("channel_key", "instance_id", "generation")
            },
        )
        outcome_value = _string(data.get("outcome"), "outcome")
        try:
            outcome = ResponseOutcome(outcome_value)
        except ValueError as exc:
            raise _error(
                "unsupported response outcome",
                path=("outcome",),
            ) from exc
        return cls(
            **identity.__dict__,
            response_handle=validate_response_handle(
                data.get("response_handle"),
            ),
            outcome=outcome,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode one response finalization request."""
        return {
            **super().to_mapping(),
            "response_handle": self.response_handle,
            "outcome": self.outcome.value,
        }


@dataclass(frozen=True)
class ResponseFinishResult:
    """Closed result returned by channel.response.finish."""

    response_handle: str
    outcome: ResponseOutcome
    state: str = field(default="closed", init=False)

    @classmethod
    def from_mapping(cls, value: object) -> "ResponseFinishResult":
        """Validate a response finalization result."""
        data = _object(value)
        _closed(data, {"response_handle", "outcome", "state"})
        if data.get("state") != "closed":
            raise _error(
                "response finish result must be closed",
                path=("state",),
                reason_code="SCHEMA_MISMATCH",
            )
        outcome_value = _string(data.get("outcome"), "outcome")
        try:
            outcome = ResponseOutcome(outcome_value)
        except ValueError as exc:
            raise _error(
                "unsupported response outcome",
                path=("outcome",),
            ) from exc
        return cls(
            response_handle=validate_response_handle(
                data.get("response_handle"),
            ),
            outcome=outcome,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode a response finalization result."""
        return {
            "response_handle": self.response_handle,
            "outcome": self.outcome.value,
            "state": self.state,
        }


@dataclass(frozen=True)
class HostStateParams(IdentityParams):
    """Identify a versioned, instance-scoped host state key."""

    key: str
    schema_version: int = 1
    value: object = None

    @classmethod
    def from_mapping(cls, value: object) -> "HostStateParams":
        """Validate host state request parameters."""
        data = _object(value)
        _closed(
            data,
            {
                *_IDENTITY_FIELDS,
                "key",
                "schema_version",
                "value",
            },
        )
        identity = _identity_from_fields(data)
        key = _string(data.get("key"), "key")
        if "/" in key or "\\" in key or key.startswith("."):
            raise _error(
                "host state key is not a safe relative key",
                path=("key",),
            )
        schema_version = _integer(
            data.get("schema_version", 1),
            "schema_version",
            minimum=1,
        )
        return cls(
            **identity.__dict__,
            key=key,
            schema_version=schema_version,
            value=data.get("value"),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode host state request parameters."""
        result = {
            **super().to_mapping(),
            "key": self.key,
            "schema_version": self.schema_version,
        }
        if self.value is not None:
            result["value"] = self.value
        return result


METHOD_SCHEMAS: dict[str, type[Any]] = {
    "channel.auth.required": AuthRequiredParams,
    "channel.management.execute": ManagementRequest,
    "channel.health": IdentityParams,
    "channel.generation_status": IdentityParams,
    "channel.stop": IdentityParams,
    "channel.send": SendParams,
    "channel.reaction": ReactionParams,
    "channel.response.finish": ResponseFinishParams,
    "event.batch": EventBatchParams,
    "delivery.update": DeliveryUpdateParams,
    "ingress.endpoint.register": EndpointParams,
    "ingress.endpoint.update": EndpointParams,
    "ingress.endpoint.unregister": IdentityParams,
    "request.cancel": CancelParams,
    "host.state.get": HostStateParams,
    "host.state.put": HostStateParams,
    "host.state.delete": HostStateParams,
    "host.receipt.get": HostStateParams,
    "host.receipt.put": HostStateParams,
}


def validate_method_params(method: str, params: object) -> Any:
    """Validate params for a registered method, if one has a DTO."""
    if method == "runner.hello":
        from .shared import SharedHelloParams

        return SharedHelloParams.from_mapping(params)
    dto_type = METHOD_SCHEMAS.get(method)
    if dto_type is None:
        if params is None:
            return None
        return _object(params)
    return dto_type.from_mapping(params)

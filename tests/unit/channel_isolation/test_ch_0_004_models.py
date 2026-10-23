# -*- coding: utf-8 -*-
"""Tests for CH-0-004 JSON-RPC and Channel protocol DTOs."""

from __future__ import annotations

import pytest

from qwenpaw.channel_protocol import (
    ApprovalSeverity,
    EndpointParams,
    HelloParams,
    HostStateParams,
    InboundEvent,
    DeliveryState,
    OutboundResult,
    PROTOCOL_VERSION,
    ProtocolValidationError,
    RpcErrorObject,
    RpcRequest,
    RpcResponse,
    ReactionParams,
    ResponseFinishParams,
    ResponseFinishResult,
    ResponseOutcome,
    SendParams,
    OutboundOperation,
    StreamType,
    parse_rpc_message,
    validate_content_part,
)
from tests.unit.channel_isolation._ch_0_004_support import _hello


def _identity() -> dict[str, object]:
    """Return a valid control identity fixture."""
    return {
        "channel_key": "voice",
        "instance_id": "instance-1",
        "generation": 7,
    }


def test_rpc_envelopes_round_trip_and_reject_unknown_fields() -> None:
    """Requests and responses retain JSON-RPC 2.0 envelope semantics."""
    request = RpcRequest.from_mapping(
        {"jsonrpc": "2.0", "id": "r1", "method": "health", "params": {}},
    )
    assert request.to_mapping()["method"] == "health"
    response = RpcResponse.from_mapping(
        {"jsonrpc": "2.0", "id": "r1", "result": None},
    )
    assert response.to_mapping()["result"] is None
    assert parse_rpc_message(request.to_mapping()) == request
    with pytest.raises(ProtocolValidationError) as exc_info:
        RpcRequest.from_mapping(
            {"jsonrpc": "2.0", "id": "r1", "method": "health", "extra": 1},
        )
    assert exc_info.value.reason_code == "SCHEMA_MISMATCH"


def test_rpc_error_uses_integer_code_and_stable_reason_data() -> None:
    """Stable business reasons remain JSON-RPC-compliant integers plus data."""
    error = RpcErrorObject(
        -32010,
        "invalid state",
        {"reason_code": "INVALID_STATE_TRANSITION"},
    )
    assert error.to_mapping() == {
        "code": -32010,
        "message": "invalid state",
        "data": {"reason_code": "INVALID_STATE_TRANSITION"},
    }


def test_rpc_parse_error_allows_only_error_response_null_id() -> None:
    """Only uncorrelated JSON-RPC errors may carry a null response ID."""
    response = RpcResponse.from_mapping(
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Parse error"},
        },
    )
    assert response.id is None
    assert response.to_mapping()["id"] is None
    with pytest.raises(ProtocolValidationError) as invalid_success:
        RpcResponse.from_mapping(
            {"jsonrpc": "2.0", "id": None, "result": None},
        )
    assert invalid_success.value.reason_code == "SCHEMA_MISMATCH"


def test_hello_requires_closed_protocol_and_source_identity() -> None:
    """Hello v1 requires one version and one exact source revision."""
    mapping = _hello().to_mapping()
    assert mapping["protocol_version"] == PROTOCOL_VERSION == 1
    assert mapping["source_revision"] == "4" * 64
    assert "protocol_min" not in mapping
    assert "protocol_max" not in mapping

    missing = dict(mapping)
    missing.pop("protocol_version")
    with pytest.raises(ProtocolValidationError) as absent:
        HelloParams.from_mapping(missing)
    assert absent.value.reason_code == "SCHEMA_MISMATCH"

    legacy = {
        **mapping,
        "protocol_min": 1,
        "protocol_max": 1,
    }
    with pytest.raises(ProtocolValidationError) as ranged:
        HelloParams.from_mapping(legacy)
    assert ranged.value.reason_code == "SCHEMA_MISMATCH"

    missing_source = dict(mapping)
    missing_source.pop("source_revision")
    with pytest.raises(ProtocolValidationError) as absent_source:
        HelloParams.from_mapping(missing_source)
    assert absent_source.value.reason_code == "SCHEMA_MISMATCH"

    for invalid_source in ("4" * 63, "A" * 64):
        invalid = {**mapping, "source_revision": invalid_source}
        with pytest.raises(ProtocolValidationError):
            HelloParams.from_mapping(invalid)


def test_media_locator_and_send_schema_are_closed() -> None:
    """Outbound media carries locators, never inline binary content."""
    image = validate_content_part(
        {"type": "image", "image_url": "https://example/image"},
    )
    assert image["image_url"].startswith("https://")
    send = SendParams.from_mapping(
        {
            **_identity(),
            "delivery_id": "delivery-1",
            "to_handle": "call-1",
            "content_parts": [image],
        },
    )
    assert send.content_parts[0]["type"] == "image"
    assert send.operation is OutboundOperation.MESSAGE_CREATE
    with pytest.raises(ProtocolValidationError):
        validate_content_part(
            {
                "type": "image",
                "image_url": "https://example/image",
                "bytes": "bad",
            },
        )


def test_outbound_operation_dtos_are_closed_and_platform_independent() -> None:
    """Send and reaction DTOs express stable operations without native IDs."""
    approval = SendParams.from_mapping(
        {
            **_identity(),
            "delivery_id": "approval-1",
            "to_handle": "chat-1",
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": "Approve?"}],
            "approval": {
                "request_id": "request-1",
                "tool_name": "shell",
                "severity": "high",
            },
        },
    )
    assert approval.approval is not None
    assert approval.approval.severity is ApprovalSeverity.HIGH
    stream_start = SendParams.from_mapping(
        {
            **_identity(),
            "delivery_id": "stream-1",
            "to_handle": "chat-1",
            "operation": "stream.start",
            "stream_type": "message",
            "sequence": 0,
            "accumulated_text": "",
        },
    )
    assert stream_start.stream_type is StreamType.MESSAGE
    stream_delta = SendParams.from_mapping(
        {
            **_identity(),
            "delivery_id": "stream-delta-1",
            "to_handle": "chat-1",
            "operation": "stream.delta",
            "target_delivery_id": "stream-1",
            "stream_type": "message",
            "sequence": 1,
            "accumulated_text": "hello",
        },
    )
    assert stream_delta.operation is OutboundOperation.STREAM_DELTA
    update = SendParams.from_mapping(
        {
            **_identity(),
            "delivery_id": "update-1",
            "to_handle": "chat-1",
            "operation": "message.update",
            "target_delivery_id": "stream-1",
            "sequence": 2,
            "content_parts": [{"type": "text", "text": "hello"}],
        },
    )
    assert update.target_delivery_id == "stream-1"
    reaction = ReactionParams.from_mapping(
        {
            **_identity(),
            "delivery_id": "reaction-1",
            "to_handle": "chat-1",
            "target_delivery_id": "stream-1",
            "reaction": "completed",
        },
    )
    assert reaction.to_mapping()["reaction"] == "completed"
    with pytest.raises(ProtocolValidationError):
        SendParams.from_mapping(
            {
                **approval.to_mapping(),
                "platform_card": {"tag": "interactive"},
            },
        )
    with pytest.raises(ProtocolValidationError):
        ReactionParams.from_mapping(
            {
                **reaction.to_mapping(),
                "reaction": "DONE",
            },
        )


def test_response_scope_dtos_and_opaque_handle_validation() -> None:
    """Response finalization remains closed and platform-independent."""
    params = ResponseFinishParams.from_mapping(
        {
            **_identity(),
            "response_handle": "feishu:reply:event-1",
            "outcome": "completed",
        },
    )
    assert params.outcome is ResponseOutcome.COMPLETED
    result = ResponseFinishResult.from_mapping(
        {
            "response_handle": params.response_handle,
            "outcome": "completed",
            "state": "closed",
        },
    )
    assert result.to_mapping()["state"] == "closed"
    event = {
        "event_id": "event-1",
        "event_kind": "message.received",
        "channel_key": "voice",
        "instance_id": "instance-1",
        "generation": 7,
        "conversation": {"id": "chat-1", "type": "group"},
        "sender_id": "sender-1",
        "acl_sender_id": "sender-1",
        "sender_name": "Sender",
        "content_parts": [{"type": "text", "text": "hello"}],
        "metadata": {},
        "response_handle": params.response_handle,
    }
    assert (
        InboundEvent.from_mapping(event).to_mapping()["response_handle"]
        == params.response_handle
    )
    with pytest.raises(ProtocolValidationError):
        ResponseFinishParams.from_mapping(
            {
                **params.to_mapping(),
                "response_handle": "",
            },
        )
    with pytest.raises(ProtocolValidationError):
        ResponseFinishParams.from_mapping(
            {
                **params.to_mapping(),
                "response_handle": "bad\nhandle",
            },
        )
    with pytest.raises(ProtocolValidationError):
        ResponseFinishParams.from_mapping(
            {
                **params.to_mapping(),
                "outcome": "unknown",
            },
        )


@pytest.mark.parametrize(
    "missing_field",
    ["channel_key", "instance_id", "generation"],
)
def test_response_finish_requires_complete_identity(
    missing_field: str,
) -> None:
    """Missing response identity fields use stable schema errors."""
    payload = {
        **_identity(),
        "response_handle": "response-1",
        "outcome": "completed",
    }
    payload.pop(missing_field)
    with pytest.raises(ProtocolValidationError) as exc_info:
        ResponseFinishParams.from_mapping(payload)
    assert exc_info.value.reason_code == "SCHEMA_MISMATCH"
    assert exc_info.value.path == (missing_field,)


def test_outbound_result_is_closed_terminal_and_bound_to_delivery() -> None:
    """Outbound results expose only stable terminal delivery fields."""
    result = OutboundResult.from_mapping(
        {
            "delivery_id": "delivery-1",
            "state": "unknown",
            "reason_code": "PLATFORM_RESULT_UNKNOWN",
            "retryable": False,
        },
    )
    assert result.state is DeliveryState.UNKNOWN
    assert result.to_mapping() == {
        "delivery_id": "delivery-1",
        "state": "unknown",
        "reason_code": "PLATFORM_RESULT_UNKNOWN",
        "retryable": False,
    }
    for invalid in (
        {"delivery_id": "delivery-1", "state": "sending"},
        {"delivery_id": "delivery-1", "state": "accepted"},
        {
            "delivery_id": "delivery-1",
            "state": "acknowledged",
            "platform_message_id": "native-1",
        },
    ):
        with pytest.raises(ProtocolValidationError):
            OutboundResult.from_mapping(invalid)


@pytest.mark.parametrize(
    "params",
    [
        {
            "operation": "stream.start",
            "stream_type": "message",
            "sequence": 1,
            "accumulated_text": "",
        },
        {
            "operation": "stream.delta",
            "target_delivery_id": "stream-1",
            "stream_type": "message",
            "sequence": 0,
            "accumulated_text": "hello",
        },
        {
            "operation": "message.update",
            "target_delivery_id": "stream-1",
            "sequence": 1,
        },
    ],
)
def test_outbound_operation_field_combinations_are_strict(
    params: dict[str, object],
) -> None:
    """Each outbound operation accepts only its required field shape."""
    with pytest.raises(ProtocolValidationError):
        SendParams.from_mapping(
            {
                **_identity(),
                "delivery_id": "invalid-1",
                "to_handle": "chat-1",
                **params,
            },
        )


def test_endpoint_rejects_unauthenticated_external_binding() -> None:
    """A non-loopback endpoint cannot be committed without auth."""
    with pytest.raises(ProtocolValidationError) as exc_info:
        EndpointParams.from_mapping(
            {
                **_identity(),
                "protocol": "http",
                "host": "0.0.0.0",
                "port": 8080,
                "path": "/voice",
                "public_base_url": None,
                "readiness": "ready",
                "bound_externally": True,
                "auth_required": False,
                "quiescing": False,
            },
        )
    assert exc_info.value.reason_code == "AUTH_FAILED"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "example.test"])
def test_endpoint_derives_external_binding_from_host(host: str) -> None:
    """Core derives external exposure instead of trusting the DTO flag."""
    with pytest.raises(ProtocolValidationError) as exc_info:
        EndpointParams.from_mapping(
            {
                **_identity(),
                "protocol": "http",
                "host": host,
                "port": 8080,
                "path": "/voice",
                "public_base_url": None,
                "readiness": "ready",
                "bound_externally": False,
                "auth_required": False,
                "quiescing": False,
            },
        )
    assert exc_info.value.reason_code == "AUTH_FAILED"


def test_endpoint_loopback_is_not_external() -> None:
    """Loopback endpoint hosts may omit authentication."""
    endpoint = EndpointParams.from_mapping(
        {
            **_identity(),
            "protocol": "http",
            "host": "::1",
            "port": 8080,
            "path": "/voice",
            "public_base_url": None,
            "readiness": "ready",
            "bound_externally": True,
            "auth_required": False,
            "quiescing": False,
        },
    )
    assert endpoint.bound_externally is False


def test_host_state_key_is_relative() -> None:
    """Host state stays instance-scoped and rejects path traversal."""
    params = HostStateParams.from_mapping({**_identity(), "key": "checkpoint"})
    assert params.key == "checkpoint"
    with pytest.raises(ProtocolValidationError):
        HostStateParams.from_mapping({**_identity(), "key": "../escape"})

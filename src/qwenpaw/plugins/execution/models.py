# -*- coding: utf-8 -*-
"""Data-only JSON-RPC envelopes and plugin identity."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
from .errors import ProtocolValidationError

JSONRPC_VERSION = "2.0"
MAX_METHOD_LENGTH = 128


def _error(
    message: str,
    *,
    path: tuple[str | int, ...] = (),
    reason_code: str = "INVALID_PARAMS",
) -> ProtocolValidationError:
    """Create a stable DTO validation error."""
    return ProtocolValidationError(
        message,
        path=path,
        reason_code=reason_code,
    )


def _object(
    value: object,
    *,
    path: tuple[str | int, ...] = (),
) -> dict[str, Any]:
    """Require a JSON object and copy it to a mutable mapping."""
    if not isinstance(value, Mapping):
        raise _error("value must be an object", path=path)
    if any(not isinstance(key, str) for key in value):
        raise _error("object keys must be strings", path=path)
    return dict(value)


def _closed(
    value: Mapping[str, Any],
    allowed: set[str],
    *,
    path: tuple[str | int, ...] = (),
) -> None:
    """Reject fields not declared by a v1 closed DTO."""
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _error(
            f"unknown field: {unknown[0]}",
            path=path + (unknown[0],),
            reason_code="SCHEMA_MISMATCH",
        )


def _rpc_object(value: object, allowed: set[str]) -> dict[str, Any]:
    """Validate the shared JSON-RPC object prefix."""
    data = _object(value)
    _closed(data, allowed)
    if data.get("jsonrpc") != JSONRPC_VERSION:
        raise _error(
            "jsonrpc must be '2.0'",
            path=("jsonrpc",),
            reason_code="PROTOCOL_MISMATCH",
        )
    return data


def _string(
    value: object,
    name: str,
    *,
    path: tuple[str | int, ...] = (),
    non_empty: bool = True,
) -> str:
    """Require a JSON string."""
    if not isinstance(value, str) or (non_empty and not value):
        raise _error(
            (
                f"{name} must be a non-empty string"
                if non_empty
                else f"{name} must be a string"
            ),
            path=path + (name,),
        )
    return value


def _integer(
    value: object,
    name: str,
    *,
    path: tuple[str | int, ...] = (),
    minimum: int | None = None,
) -> int:
    """Require a JSON integer, excluding booleans."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise _error(f"{name} must be an integer", path=path + (name,))
    if minimum is not None and value < minimum:
        raise _error(
            f"{name} must be at least {minimum}",
            path=path + (name,),
        )
    return value


def _optional_string(
    value: Mapping[str, Any],
    name: str,
    *,
    path: tuple[str | int, ...] = (),
    non_empty: bool = True,
) -> str | None:
    """Read an optional nullable string."""
    if name not in value or value[name] is None:
        return None
    return _string(
        value[name],
        name,
        path=path,
        non_empty=non_empty,
    )


def _request_id(value: object) -> str | int:
    """Validate a JSON-RPC request identifier."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _error("request id must be a string or integer", path=("id",))
    if isinstance(value, str) and not value:
        raise _error("request id must not be empty", path=("id",))
    return value


@dataclass(frozen=True)
class RpcErrorObject:
    """JSON-RPC error object with a stable string reason in data."""

    code: int
    message: str
    data: object = None

    def to_mapping(self) -> dict[str, Any]:
        """Encode the error object."""
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        return result

    @classmethod
    def from_mapping(cls, value: object) -> "RpcErrorObject":
        """Validate a JSON-RPC error object."""
        data = _object(value, path=("error",))
        _closed(data, {"code", "message", "data"}, path=("error",))
        code = _integer(data.get("code"), "code", path=("error",))
        message = _string(data.get("message"), "message", path=("error",))
        return cls(code=code, message=message, data=data.get("data"))


@dataclass(frozen=True)
class RpcRequest:
    """JSON-RPC request envelope."""

    id: str | int
    method: str
    params: Mapping[str, Any] | list[Any] | None = None

    def to_mapping(self) -> dict[str, Any]:
        """Encode the request envelope."""
        result: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": self.id,
            "method": self.method,
        }
        if self.params is not None:
            result["params"] = self.params
        return result

    @classmethod
    def from_mapping(cls, value: object) -> "RpcRequest":
        """Validate a request envelope."""
        data = _rpc_object(value, {"jsonrpc", "id", "method", "params"})
        if "id" not in data:
            raise _error(
                "request must contain id",
                path=("id",),
                reason_code="SCHEMA_MISMATCH",
            )
        request_id = _request_id(data["id"])
        method = _string(data.get("method"), "method")
        if len(method) > MAX_METHOD_LENGTH:
            raise _error("method is too long", path=("method",))
        params = data.get("params")
        if params is not None and not isinstance(params, (Mapping, list)):
            raise _error("params must be an object or array", path=("params",))
        return cls(id=request_id, method=method, params=params)


@dataclass(frozen=True)
class RpcNotification:
    """JSON-RPC notification envelope."""

    method: str
    params: Mapping[str, Any] | list[Any] | None = None

    def to_mapping(self) -> dict[str, Any]:
        """Encode the notification envelope."""
        result: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "method": self.method,
        }
        if self.params is not None:
            result["params"] = self.params
        return result

    @classmethod
    def from_mapping(cls, value: object) -> "RpcNotification":
        """Validate a notification envelope."""
        data = _rpc_object(value, {"jsonrpc", "method", "params"})
        method = _string(data.get("method"), "method")
        params = data.get("params")
        if params is not None and not isinstance(params, (Mapping, list)):
            raise _error("params must be an object or array", path=("params",))
        return cls(method=method, params=params)


@dataclass(frozen=True)
class RpcResponse:
    """JSON-RPC response envelope."""

    id: str | int | None
    result: object = None
    error: RpcErrorObject | None = None

    def __post_init__(self) -> None:
        """Require exactly one of result or error semantically."""
        if self.error is not None and self.result is not None:
            raise ValueError("response cannot contain both result and error")
        if self.id is None and self.error is None:
            raise ValueError("only error responses may use a null id")

    def to_mapping(self) -> dict[str, Any]:
        """Encode the response envelope."""
        result: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": self.id,
        }
        if self.error is not None:
            result["error"] = self.error.to_mapping()
        else:
            result["result"] = self.result
        return result

    @classmethod
    def from_mapping(cls, value: object) -> "RpcResponse":
        """Validate a response envelope."""
        data = _rpc_object(value, {"jsonrpc", "id", "result", "error"})
        if "id" not in data:
            raise _error("response must contain id", path=("id",))
        has_result = "result" in data
        has_error = "error" in data
        if has_result == has_error:
            raise _error(
                "response must contain exactly one result or error",
                reason_code="SCHEMA_MISMATCH",
            )
        if data["id"] is None:
            if not has_error:
                raise _error(
                    "only error responses may use a null id",
                    path=("id",),
                    reason_code="SCHEMA_MISMATCH",
                )
            response_id = None
        else:
            response_id = _request_id(data["id"])
        return cls(
            id=response_id,
            result=data.get("result"),
            error=(
                RpcErrorObject.from_mapping(data["error"])
                if has_error
                else None
            ),
        )


RpcMessage = RpcRequest | RpcResponse | RpcNotification


def parse_rpc_message(value: object) -> RpcMessage:
    """Parse one JSON-RPC request, response, or notification mapping."""
    data = _object(value)
    if "method" in data and "id" in data:
        return RpcRequest.from_mapping(data)
    if "method" in data:
        return RpcNotification.from_mapping(data)
    return RpcResponse.from_mapping(data)


@dataclass(frozen=True)
class CancelParams:
    """Notification parameters for request cancellation."""

    request_id: str | int
    reason: str | None = None

    @classmethod
    def from_mapping(cls, value: object) -> "CancelParams":
        """Validate cancellation parameters."""
        data = _object(value)
        _closed(data, {"request_id", "reason"})
        if "request_id" not in data:
            raise _error(
                "missing required field: request_id",
                path=("request_id",),
            )
        return cls(
            request_id=_request_id(data["request_id"]),
            reason=_optional_string(data, "reason"),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode cancellation parameters."""
        result: dict[str, Any] = {"request_id": self.request_id}
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True)
class PluginIdentity:
    """Identity of one explicitly launched component generation."""

    plugin_id: str
    instance_id: str
    generation: int

    def __post_init__(self) -> None:
        _string(self.plugin_id, "plugin_id")
        _string(self.instance_id, "instance_id")
        _integer(self.generation, "generation", minimum=1)

    def to_mapping(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_mapping(cls, value: object) -> PluginIdentity:
        data = _object(value)
        _closed(data, {"plugin_id", "instance_id", "generation"})
        return cls(
            _string(data.get("plugin_id"), "plugin_id"),
            _string(data.get("instance_id"), "instance_id"),
            _integer(data.get("generation"), "generation", minimum=1),
        )


def validate_method_params(_method: str, params: object) -> Any:
    """Leave application schemas to the caller; envelopes enforce JSON data."""
    return params

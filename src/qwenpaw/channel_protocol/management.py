# -*- coding: utf-8 -*-
"""Closed, SDK-free data contracts for explicit Channel management."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
import math
from typing import Any, NoReturn, cast
from uuid import UUID

from .errors import ProtocolValidationError


class ManagementOperation(StrEnum):
    QRCODE_FETCH = "qrcode.fetch"
    QRCODE_POLL = "qrcode.poll"
    CONNECTION_VERIFY = "connection.verify"


class ManagementOutcome(StrEnum):
    OK = "ok"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class VerificationLevel(StrEnum):
    REACHABILITY = "reachability"
    CREDENTIALS = "credentials"


class VerificationVerdict(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class ManagementReason(StrEnum):
    MANAGEMENT_BUSY = "MANAGEMENT_BUSY"
    MANAGEMENT_CLOSED = "MANAGEMENT_CLOSED"
    PLUGIN_NOT_INSTALLED = "PLUGIN_NOT_INSTALLED"
    PLUGIN_DISABLED = "PLUGIN_DISABLED"
    CHANNEL_UNAVAILABLE = "CHANNEL_UNAVAILABLE"
    MANAGEMENT_UNSUPPORTED = "MANAGEMENT_UNSUPPORTED"
    MANAGEMENT_INVALID_REQUEST = "MANAGEMENT_INVALID_REQUEST"
    MANAGEMENT_INVALID_RESULT = "MANAGEMENT_INVALID_RESULT"
    MANAGEMENT_TIMEOUT = "MANAGEMENT_TIMEOUT"
    MANAGEMENT_CANCELLED = "MANAGEMENT_CANCELLED"
    PLATFORM_RESULT_UNKNOWN = "PLATFORM_RESULT_UNKNOWN"
    MANAGEMENT_CLEANUP_FAILED = "MANAGEMENT_CLEANUP_FAILED"
    PLATFORM_REQUEST_FAILED = "PLATFORM_REQUEST_FAILED"
    PLATFORM_REJECTED = "PLATFORM_REJECTED"
    VERIFICATION_UNSUPPORTED = "VERIFICATION_UNSUPPORTED"
    ACCOUNT_IN_USE = "ACCOUNT_IN_USE"
    SOURCE_REVISION_MISMATCH = "SOURCE_REVISION_MISMATCH"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    DESCRIPTOR_OUTSIDE_CODE_ROOT = "DESCRIPTOR_OUTSIDE_CODE_ROOT"
    DEPENDENCY_PATH_INVALID = "DEPENDENCY_PATH_INVALID"
    HELLO_REJECTED = "HELLO_REJECTED"
    ENTRYPOINT_INVALID = "ENTRYPOINT_INVALID"
    ENTRYPOINT_OUTSIDE_CODE_ROOT = "ENTRYPOINT_OUTSIDE_CODE_ROOT"
    ENTRYPOINT_IMPORT_FAILED = "ENTRYPOINT_IMPORT_FAILED"
    DEPENDENCY_UNSATISFIED = "DEPENDENCY_UNSATISFIED"
    DEPENDENCY_METADATA_INVALID = "DEPENDENCY_METADATA_INVALID"
    DEPENDENCY_ENVIRONMENT_AMBIGUOUS = "DEPENDENCY_ENVIRONMENT_AMBIGUOUS"
    DEPENDENCY_REPAIR_REQUIRED = "DEPENDENCY_REPAIR_REQUIRED"
    DEPENDENCY_ORIGIN_INVALID = "DEPENDENCY_ORIGIN_INVALID"
    PROBE_NETWORK_OR_PROCESS_DENIED = "PROBE_NETWORK_OR_PROCESS_DENIED"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
    CHANNEL_RUNTIME_IDENTITY_MISMATCH = "CHANNEL_RUNTIME_IDENTITY_MISMATCH"


MANAGEMENT_METHOD = "channel.management.execute"
MANAGEMENT_CAPABILITIES = {
    "qrcode.fetch": "channel.management.qrcode.v1",
    "qrcode.poll": "channel.management.qrcode.v1",
    "connection.verify": "channel.management.verify.v1",
}
_IDENTITY_FIELDS = (
    "request_id",
    "plugin_id",
    "workspace_id",
    "channel_key",
    "instance_id",
    "generation",
    "source_revision",
    "operation",
)
_AUTH_FIELDS = {
    "wechat": {"bot_token", "base_url"},
    "qq": {"app_id", "client_secret", "user_openid"},
    "wecom": {"bot_id", "secret"},
    "dingtalk": {"client_id", "client_secret"},
    "feishu": {"app_id", "app_secret", "open_id", "tenant_brand"},
}


def management_credential_keys(
    channel_key: str,
    schema: Mapping,
) -> frozenset[str]:
    """Derive authority from trusted metadata, never an RPC allowlist."""
    return frozenset(
        {
            name
            for name, spec in schema.get("properties", {}).items()
            if isinstance(spec, Mapping) and spec.get("type") == "string"
        }
        | _AUTH_FIELDS.get(channel_key, set())
        | {"fail_reason"},
    )


def _invalid() -> NoReturn:
    raise ProtocolValidationError(
        "invalid management data",
        reason_code="MANAGEMENT_INVALID_REQUEST",
    )


def _closed(
    value: object,
    fields: Collection[str],
    *,
    optional: Collection[str] = (),
) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or not set(fields) <= set(value)
        or not set(value) <= set(fields) | set(optional)
    ):
        _invalid()
    return dict(cast(Mapping[str, Any], value))


def _text(value: object, *, limit: int = 65536, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        _invalid()
    try:
        if len(value.encode("utf-8")) > limit:
            _invalid()
    except UnicodeError:
        _invalid()
    return value


def _choice(value: object, choices: Collection[str]) -> str:
    if not isinstance(value, str) or not any(
        value == item for item in choices
    ):
        _invalid()
    return value


def management_options(
    value: object,
    *,
    fields: Collection[str] | None = None,
    forbidden: Collection[str] = (),
) -> dict[str, str]:
    """Validate bounded transient strings without changing saved config."""
    if not isinstance(value, Mapping) or len(value) > 16:
        _invalid()
    for name, item in value.items():
        _text(name, limit=128)
        _text(item, limit=8192, nonempty=False)
    if (fields is not None and not set(value) <= set(fields)) or set(
        value,
    ).intersection(forbidden):
        _invalid()
    return dict(cast(Mapping[str, str], value))


def _json(value: object) -> Any:
    if isinstance(value, str):
        return str(value)
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, Mapping) and all(isinstance(k, str) for k in value):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json(v) for v in value]
    _invalid()


def _packet(value: object, fields: Collection[str]) -> dict[str, Any]:
    try:
        data = _json(_closed(value, fields))
        if (
            len(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            > 65536
        ):
            _invalid()
        return data
    except (RecursionError, UnicodeError, TypeError, ValueError):
        _invalid()


def _identity(data: Mapping) -> None:
    for name in _IDENTITY_FIELDS:
        if name not in {"generation", "operation"}:
            _text(data[name])
    try:
        UUID(data["request_id"])
    except (ValueError, AttributeError):
        _invalid()
    if type(data["generation"]) is not int or data["generation"] <= 0:
        _invalid()
    digest = data["source_revision"]
    if len(digest) != 64 or any(
        c not in "0123456789abcdefABCDEF" for c in digest
    ):
        _invalid()
    _choice(data["operation"], ManagementOperation)


def _reason(value: object, *, required: bool) -> None:
    if required:
        _choice(value, ManagementReason)
    elif value is not None:
        _invalid()


@dataclass(frozen=True)
class _ManagementIdentity:
    request_id: str
    plugin_id: str
    workspace_id: str
    channel_key: str
    instance_id: str
    generation: int
    source_revision: str
    operation: str

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ManagementRequest(_ManagementIdentity):
    timeout_ms: int
    parameters: Mapping[str, Any] = field(repr=False)

    @classmethod
    def from_mapping(cls, value: object) -> ManagementRequest:
        data = _packet(value, (*_IDENTITY_FIELDS, "timeout_ms", "parameters"))
        _identity(data)
        if (
            type(data["timeout_ms"]) is not int
            or not 1 <= data["timeout_ms"] <= 65000
        ):
            _invalid()
        fields = {
            "qrcode.fetch": ("config",),
            "qrcode.poll": ("config", "continuation"),
            "connection.verify": ("config", "level"),
        }[data["operation"]]
        parameters = _closed(
            data["parameters"],
            fields,
            optional=(
                ()
                if data["operation"] == "connection.verify"
                else ("options",)
            ),
        )
        if not isinstance(parameters["config"], dict):
            _invalid()
        if data["operation"] == "qrcode.poll":
            _text(parameters["continuation"], limit=16384)
        elif data["operation"] == "connection.verify":
            _choice(parameters["level"], VerificationLevel)
        if "options" in parameters:
            management_options(parameters["options"])
        return cls(**data)


@dataclass(frozen=True)
class ManagementResult(_ManagementIdentity):
    outcome: str
    reason_code: str | None
    result: Mapping[str, Any] | None = field(repr=False)

    @classmethod
    def from_mapping(cls, value: object) -> ManagementResult:
        try:
            data = _packet(
                value,
                (*_IDENTITY_FIELDS, "outcome", "reason_code", "result"),
            )
            _identity(data)
            _choice(data["outcome"], ManagementOutcome)
            failed = data["outcome"] != "ok"
            _reason(data["reason_code"], required=failed)
            if failed:
                if data["result"] is not None:
                    _invalid()
                return cls(**data)
            operation = data["operation"]
            fields: dict[str, tuple[str, ...]] = {
                "qrcode.fetch": ("scan_url", "continuation"),
                "qrcode.poll": ("status", "credentials"),
                "connection.verify": (
                    "level",
                    "verdict",
                    "reason_code",
                    "notes",
                ),
            }[operation]
            optional: dict[str, set[str]] = {
                "qrcode.fetch": {"expires_in_seconds"},
                "qrcode.poll": {"metadata"},
                "connection.verify": set(),
            }[operation]
            payload = data["result"]
            if (
                not isinstance(payload, dict)
                or not set(fields) <= payload.keys()
                or not payload.keys() <= set(fields) | set(optional)
            ):
                _invalid()
            result = dict(payload)
            if operation == "qrcode.fetch":
                for name in fields:
                    _text(result[name], limit=16384)
                if "expires_in_seconds" in result and (
                    type(result["expires_in_seconds"]) is not int
                    or not 1 <= result["expires_in_seconds"] <= 7200
                ):
                    _invalid()
            elif operation == "qrcode.poll":
                _text(result["status"])
                if len(result["status"]) > 512 or not isinstance(
                    result["credentials"],
                    dict,
                ):
                    _invalid()
                for name, credential in result["credentials"].items():
                    _text(name)
                    _text(credential, limit=8192, nonempty=False)
                if "metadata" in result:
                    metadata = result["metadata"]
                    if (
                        not isinstance(metadata, dict)
                        or len(metadata) > 16
                        or metadata.keys() & result["credentials"].keys()
                    ):
                        _invalid()
                    for name, item in metadata.items():
                        _text(name, limit=128)
                        _text(item, limit=8192, nonempty=False)
            else:
                _choice(result["level"], VerificationLevel)
                _choice(result["verdict"], VerificationVerdict)
                _reason(
                    result["reason_code"],
                    required=result["verdict"] != "passed",
                )
                notes = result["notes"]
                if not isinstance(notes, list) or len(notes) > 16:
                    _invalid()
                for note in notes:
                    _text(note, nonempty=False)
                    if len(note) > 512:
                        _invalid()
            return cls(**data)
        except ProtocolValidationError:
            raise ProtocolValidationError(
                "invalid management result",
                reason_code="MANAGEMENT_INVALID_RESULT",
            ) from None

    def validate_for(
        self,
        request: ManagementRequest,
        *,
        credential_keys: Collection[str],
    ) -> None:
        """Fence result identity, check level and trusted credential fields."""
        validated = type(self).from_mapping(self.to_mapping())
        if any(
            getattr(validated, name) != getattr(request, name)
            for name in _IDENTITY_FIELDS
        ):
            raise ProtocolValidationError(
                "management identity mismatch",
                reason_code="MANAGEMENT_INVALID_RESULT",
            )
        if validated.outcome != "ok":
            return
        result = validated.result
        if result is None:
            raise ProtocolValidationError(
                "management result missing",
                reason_code="MANAGEMENT_INVALID_RESULT",
            )
        if self.operation == "qrcode.poll":
            if not set(result["credentials"]) <= set(
                credential_keys,
            ):
                raise ProtocolValidationError(
                    "management credential fields invalid",
                    reason_code="MANAGEMENT_INVALID_RESULT",
                )
        elif (
            self.operation == "connection.verify"
            and result["level"] != request.parameters["level"]
        ):
            raise ProtocolValidationError(
                "management verification level mismatch",
                reason_code="MANAGEMENT_INVALID_RESULT",
            )


def management_result(request, result=None, *, reason=None, unsupported=False):
    """Build one validated fixed-hook response without copying its identity."""
    identity = {name: getattr(request, name) for name in _IDENTITY_FIELDS}
    return ManagementResult.from_mapping(
        {
            **identity,
            "outcome": (
                "unsupported" if unsupported else "failed" if reason else "ok"
            ),
            "reason_code": reason,
            "result": result,
        },
    )

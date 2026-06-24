# -*- coding: utf-8 -*-
"""Driver runtime capability contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote, unquote, urlsplit

# Keep the concrete kind set aligned with implemented Driver protocols.  MCP
# currently exposes tools only.  Future protocols such as ACP/A2A can extend
# this Literal and _KIND_TO_PATH_SEGMENT in the same change that introduces
# their concrete handlers, so this module remains a record of implemented API
# surface rather than a bucket of aspirational kinds.
CapabilityKind = Literal["tool"]

__all__ = [
    "CapabilityExposure",
    "CapabilityKind",
    "DriverCapability",
    "DriverInvocation",
    "DriverInvocationResult",
    "DriverRuntimeInfo",
    "format_capability_id",
    "parse_capability_id",
]


@dataclass(frozen=True)
class CapabilityExposure:
    """Describe how a capability is exposed to an upper runtime."""

    as_tool: bool = False
    tool_name: str = ""
    namespace: str = ""


@dataclass(frozen=True)
class DriverCapability:
    """A protocol-neutral capability exposed by one Driver."""

    capability_id: str
    driver_name: str
    protocol: str
    kind: CapabilityKind
    action: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    exposure: CapabilityExposure = field(default_factory=CapabilityExposure)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DriverInvocation:
    """One request to execute a Driver capability."""

    capability_id: str
    payload: dict[str, Any]
    request_context: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DriverInvocationResult:
    """Result returned by DriverManager.invoke_capability."""

    ok: bool
    value: Any = None
    error_type: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DriverRuntimeInfo:
    """Public runtime status for one Driver."""

    name: str
    protocol: str
    enabled: bool
    status: str
    display_name: str = ""
    description: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def format_capability_id(
    protocol: str,
    driver_name: str,
    kind: str,
    action: str,
    name: str,
) -> str:
    """Return the stable id for a Driver capability."""
    return (
        f"driver://{_encode_part(protocol)}/"
        f"{_encode_part(driver_name)}/"
        f"{_encode_part(_kind_to_path_segment(kind))}/"
        f"{_encode_part(name)}"
        f"#{_encode_part(action)}"
    )


def parse_capability_id(capability_id: str) -> tuple[str, str, str, str, str]:
    """Parse a Driver capability id.

    Returns protocol, driver, kind, action, and name.
    """
    parsed = urlsplit(capability_id)
    path_parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "driver"
        or not parsed.netloc
        or len(path_parts) != 3
        or not parsed.fragment
    ):
        raise ValueError(f"Invalid Driver capability id: {capability_id}")

    protocol = _decode_part(parsed.netloc)
    driver_name = _decode_part(path_parts[0])
    kind = _path_segment_to_kind(_decode_part(path_parts[1]))
    name = _decode_part(path_parts[2])
    action = _decode_part(parsed.fragment)
    return protocol, driver_name, kind, action, name


_KIND_TO_PATH_SEGMENT = {"tool": "tools"}
_PATH_SEGMENT_TO_KIND = {
    path_segment: kind for kind, path_segment in _KIND_TO_PATH_SEGMENT.items()
}


def _kind_to_path_segment(kind: str) -> str:
    return _KIND_TO_PATH_SEGMENT.get(kind, kind)


def _path_segment_to_kind(path_segment: str) -> str:
    return _PATH_SEGMENT_TO_KIND.get(path_segment, path_segment)


def _encode_part(value: str) -> str:
    return quote(str(value), safe="")


def _decode_part(value: str) -> str:
    return unquote(str(value))

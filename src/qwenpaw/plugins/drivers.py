# -*- coding: utf-8 -*-
"""Host-independent Driver declarations and immutable source snapshots."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping, Protocol, TYPE_CHECKING

from .events import JSONValue
from .messages import Attachment, ContentBlock
from .resources import ResourceScope

if TYPE_CHECKING:
    from .logging import PluginLogger


def _freeze(value, seen=None):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Driver JSON numbers must be finite")
        return value
    if not isinstance(value, (Mapping, list, tuple)):
        raise TypeError("Driver values must contain only JSON data")
    seen = set() if seen is None else seen
    if id(value) in seen:
        raise ValueError("Driver JSON must not contain cycles")
    seen.add(id(value))
    try:
        if isinstance(value, Mapping):
            if any(type(key) is not str for key in value):
                raise TypeError("Driver JSON object keys must be strings")
            return MappingProxyType(
                {key: _freeze(item, seen) for key, item in value.items()},
            )
        return tuple(_freeze(item, seen) for item in value)
    finally:
        seen.remove(id(value))


def _mapping(value):
    if not isinstance(value, Mapping):
        raise TypeError("Driver JSON object must be a mapping")
    return _freeze(value)


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _schema(value):
    from jsonschema import SchemaError
    from jsonschema.validators import validator_for

    if not isinstance(value, Mapping) and type(value) is not bool:
        raise TypeError("Driver schema must be a JSON Schema object or bool")
    snapshot = _freeze(value)
    try:
        plain = _thaw(snapshot)
        validator_for(plain).check_schema(plain)
    except SchemaError as exc:
        raise ValueError("Invalid Driver JSON Schema") from exc
    return snapshot


def _strings(value, *names):
    if any(type(getattr(value, name)) is not str for name in names):
        raise TypeError("Driver identity and text fields must be strings")


def _block(block):
    if not isinstance(block, ContentBlock):
        raise TypeError(
            "Driver content must contain public ContentBlock values",
        )
    _strings(block, "type", "text", "id", "name", "arguments", "state")
    attachment = block.attachment
    if attachment is not None:
        if not isinstance(attachment, Attachment):
            raise TypeError(
                "Driver attachments must be public Attachment values",
            )
        _strings(attachment, "url", "mime_type", "name", "preview_url")
        attachment = replace(attachment)
    if not isinstance(block.output, (str, list, tuple)):
        raise TypeError("Driver block output must be text or content blocks")
    return replace(
        block,
        attachment=attachment,
        output=(
            block.output
            if isinstance(block.output, str)
            else tuple(_block(item) for item in block.output)
        ),
        metadata=_mapping(block.metadata),
        attributes=_mapping(block.attributes),
    )


@dataclass(frozen=True)
class DriverSource:
    source_id: str
    protocol: str
    endpoint: Mapping[str, JSONValue]
    config: Mapping[str, JSONValue] = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self):
        _strings(self, "source_id", "protocol")
        object.__setattr__(self, "endpoint", _mapping(self.endpoint))
        object.__setattr__(self, "config", _mapping(self.config))


@dataclass(frozen=True)
class DriverCapabilitySpec:
    name: str
    description: str
    input_schema: Mapping[str, JSONValue] | bool
    output_schema: Mapping[str, JSONValue] | bool | None = None
    tool_name: str = ""
    enabled: bool = True
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self):
        _strings(self, "name", "description", "tool_name")
        object.__setattr__(self, "input_schema", _schema(self.input_schema))
        if self.output_schema is not None:
            object.__setattr__(
                self,
                "output_schema",
                _schema(self.output_schema),
            )
        object.__setattr__(self, "metadata", _mapping(self.metadata))


@dataclass(frozen=True)
class DriverCallResult:
    content: tuple[ContentBlock, ...] = ()
    is_error: bool = False
    structured_content: JSONValue = None
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(
            self,
            "content",
            tuple(_block(b) for b in self.content),
        )
        object.__setattr__(
            self,
            "structured_content",
            _freeze(self.structured_content),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata))


@dataclass(frozen=True)
class DriverRequestContext:
    workspace_id: str
    workspace_instance_id: str
    session_id: str
    user_id: str
    channel: str
    deadline: float | None = None
    _is_cancelled: Callable[[], bool] = field(
        default=lambda: False,
        repr=False,
        compare=False,
    )

    def __post_init__(self):
        _strings(
            self,
            "workspace_id",
            "workspace_instance_id",
            "session_id",
            "user_id",
            "channel",
        )

    @property
    def cancelled(self) -> bool:
        return self._is_cancelled()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError


@dataclass(frozen=True)
class DriverCredential:
    kind: str
    revision: int
    public: Mapping[str, JSONValue]
    secrets: Mapping[str, JSONValue] = field(repr=False)

    def __post_init__(self):
        _strings(self, "kind")
        if type(self.revision) is not int:
            raise TypeError("Driver credential revision must be an integer")
        object.__setattr__(self, "public", _mapping(self.public))
        object.__setattr__(self, "secrets", _mapping(self.secrets))


class DriverCredentialAccess(Protocol):
    @property
    def aliases(self) -> tuple[str, ...]:
        ...

    async def resolve(self, alias: str) -> DriverCredential:
        ...

    async def resolve_runtime(
        self,
        alias: str,
    ) -> Mapping[str, JSONValue]:
        """Materialize declared provider values without exposing its ref."""

    async def update(
        self,
        alias: str,
        *,
        expected_revision: int,
        public: Mapping[str, JSONValue],
        secrets: Mapping[str, JSONValue],
    ) -> None:
        ...


@dataclass(frozen=True)
class DriverContext:
    plugin_id: str
    generation: int
    workspace_id: str
    workspace_instance_id: str
    source_id: str
    source_revision: int
    source: DriverSource
    resources: ResourceScope
    logger: PluginLogger
    credentials: DriverCredentialAccess
    session_scope: str = ""
    _invalidate_capabilities: Callable[[], None] = field(
        default=lambda: None,
        repr=False,
        compare=False,
    )

    def __post_init__(self):
        _strings(
            self,
            "plugin_id",
            "workspace_id",
            "workspace_instance_id",
            "source_id",
            "session_scope",
        )
        if not isinstance(self.source, DriverSource):
            raise TypeError("Driver context requires a public DriverSource")

    _subprocess_environment: (
        Callable[[], Awaitable[Mapping[str, str]]] | None
    ) = field(
        default=None,
        repr=False,
        compare=False,
    )

    async def subprocess_environment(self) -> Mapping[str, str]:
        if self._subprocess_environment is None:
            from .errors import SDKError

            raise SDKError(
                "Subprocess environment is unavailable in this context",
            )
        return await self._subprocess_environment()

    def invalidate_capabilities(self) -> None:
        self._invalidate_capabilities()


class DriverConnection(Protocol):
    async def open(self) -> None:
        ...

    async def discover(
        self,
        request: DriverRequestContext,
    ) -> tuple[DriverCapabilitySpec, ...]:
        ...

    async def invoke(
        self,
        name: str,
        arguments: Mapping[str, JSONValue],
        request: DriverRequestContext,
    ) -> DriverCallResult:
        ...

    async def close(self) -> None:
        ...


@dataclass(frozen=True)
class DriverProtocolSpec:
    protocol: str
    validate: Callable[[DriverSource], None]
    create: Callable[[DriverContext, DriverSource], DriverConnection]

    def __post_init__(self):
        _strings(self, "protocol")
        if not self.protocol or self.protocol.strip() != self.protocol:
            raise ValueError("Driver protocol must be a non-empty name")
        if not callable(self.validate) or not callable(self.create):
            raise TypeError("Driver protocol callbacks must be callable")

# -*- coding: utf-8 -*-
"""Static descriptors and metadata-only shared Runner handshake contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from importlib import metadata
import json
from pathlib import Path
import re
from typing import Any, Mapping

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .canonical import canonical_json, parse_json_value
from .descriptor import (
    Entrypoint,
    _closed_object,
    _localized_text,
    _parse_entrypoint,
)
from .errors import DescriptorValidationError, ProtocolValidationError
from .identifiers import (
    validate_channel_key,
    validate_digest,
    validate_platform_tag,
    validate_python_abi,
)
from .models import IdentityParams, _capabilities, _string
from .models import _identity_from_fields
from .requirements import canonicalize_requirements

SHARED_PROTOCOL_VERSION = 2
_DESCRIPTOR_FIELDS = frozenset(
    {
        "schema_version",
        "channel_key",
        "label",
        "process_mode",
        "dependency_mode",
        "entrypoint",
        "requirements_file",
        "config_schema",
        "config_fields",
        "capabilities",
    },
)
_HELLO_FIELDS = frozenset(
    {
        "protocol_version",
        "dependency_mode",
        "qwenpaw_version",
        "channel_key",
        "instance_id",
        "generation",
        "source_revision",
        "python_abi",
        "platform_tag",
        "dependencies",
        "marker_environment",
        "capabilities",
    },
)
_DEPENDENCY_FIELDS = frozenset(
    {"requirement", "name", "installed_version", "status"},
)


def _protocol_object(value: object, fields: frozenset[str]) -> Mapping:
    try:
        return _closed_object(value, fields)
    except DescriptorValidationError as exc:
        raise ProtocolValidationError(str(exc)) from exc


def _schema_json_copy(schema: Mapping) -> dict:
    """Detach schema data with lossless, standard-JSON numeric values."""

    def exact(value):
        if isinstance(value, Mapping):
            return {key: exact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [exact(item) for item in value]
        if isinstance(value, float):
            # Only this schema boundary accepts native floats. Canonical JSON
            # retains its existing binary-float rejection everywhere else.
            return Decimal(str(float(value)))
        return value

    def native_number(value):
        number = float(value)
        # JSON's emitted numeric token must retain the original decimal value;
        # rejecting unrepresentable precision is preferable to silent rounding.
        encoded = json.dumps(number, allow_nan=False)
        if Decimal(encoded) != value:
            raise DescriptorValidationError(
                "config_schema number cannot round-trip through standard JSON",
            )
        return number

    detached = exact(schema)
    # Preserve finite/size/int64/NFC/duplicate-key canonical validation without
    # emitting canonical bytes as the schema's standard-JSON representation.
    canonical_json(detached)
    return json.loads(
        json.dumps(detached, default=native_number, allow_nan=False),
    )


@dataclass(frozen=True)
class SharedChannelDescriptor:
    """Candidate schema v2, independent of dedicated environment hashes."""

    channel_key: str
    label: Mapping[str, str]
    entrypoint: Entrypoint
    config_schema: Mapping[str, Any]
    config_fields: tuple[str, ...]
    capabilities: tuple[str, ...]
    schema_version: int = 2
    process_mode: str = "runner_process"
    dependency_mode: str = "shared"
    requirements_file: str = "requirements.txt"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SharedChannelDescriptor:
        """Read a closed descriptor without importing its implementation."""
        data = _closed_object(value, _DESCRIPTOR_FIELDS)
        if (
            type(data["schema_version"]) is not int
            or data["schema_version"] != 2
        ):
            raise DescriptorValidationError("schema_version must be integer 2")
        for name, expected in (
            ("process_mode", "runner_process"),
            ("dependency_mode", "shared"),
            ("requirements_file", "requirements.txt"),
        ):
            if data[name] != expected:
                raise DescriptorValidationError(f"{name} must be {expected}")
        label = _localized_text(data["label"], "label")
        if not isinstance(label, Mapping) or not all(
            label.get(k) for k in ("en", "zh")
        ):
            raise DescriptorValidationError("label requires en and zh")
        schema = data["config_schema"]
        if not isinstance(schema, Mapping) or schema.get("type") != "object":
            raise DescriptorValidationError(
                "config_schema must describe an object",
            )
        properties = schema.get("properties")
        if not isinstance(properties, Mapping) or any(
            not isinstance(key, str) or not isinstance(prop, Mapping)
            for key, prop in properties.items()
        ):
            raise DescriptorValidationError(
                "config_schema properties are invalid",
            )
        fields = data["config_fields"]
        if (
            not isinstance(fields, list)
            or any(not isinstance(name, str) for name in fields)
            or len(set(fields)) != len(fields)
            or set(fields) != set(properties)
        ):
            raise DescriptorValidationError(
                "config_fields must match schema properties exactly",
            )
        try:
            capabilities = _capabilities(data["capabilities"])
        except ProtocolValidationError as exc:
            raise DescriptorValidationError(str(exc)) from exc
        return cls(
            channel_key=validate_channel_key(data["channel_key"]),
            label=label,
            entrypoint=_parse_entrypoint(data["entrypoint"], "runner_process"),
            config_schema=_schema_json_copy(schema),
            config_fields=tuple(fields),
            capabilities=capabilities,
        )

    @classmethod
    def from_json(cls, data: str | bytes) -> SharedChannelDescriptor:
        """Parse JSON without executable discovery."""
        return cls.from_mapping(parse_json_value(data))

    @classmethod
    def load(cls, path: str | Path) -> SharedChannelDescriptor:
        """Load a candidate channel.json."""
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def to_mapping(self) -> dict[str, Any]:
        """Return the static descriptor JSON shape."""
        return {
            "schema_version": self.schema_version,
            "channel_key": self.channel_key,
            "label": dict(self.label),
            "process_mode": self.process_mode,
            "dependency_mode": self.dependency_mode,
            "entrypoint": self.entrypoint.to_mapping(),
            "requirements_file": self.requirements_file,
            "config_schema": _schema_json_copy(self.config_schema),
            "config_fields": list(self.config_fields),
            "capabilities": list(self.capabilities),
        }


def _read_requirements(path: str | Path) -> tuple[str, ...]:
    lines = [
        re.split(r"\s+#", line, maxsplit=1)[0].strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    try:
        result = canonicalize_requirements(lines)
        for value in result:
            _requirement(value)
        return result
    except DescriptorValidationError as exc:
        raise ProtocolValidationError(str(exc)) from exc


def _requirement(value: str) -> Requirement:
    try:
        canonical = canonicalize_requirements([value])[0]
    except DescriptorValidationError as exc:
        raise ProtocolValidationError(str(exc)) from exc
    requirement = Requirement(canonical)
    if requirement.url or requirement.extras:
        raise ProtocolValidationError(
            "Shared audit requires plain distribution requirements",
        )
    return requirement


@dataclass(frozen=True)
class DependencyStatus:
    """Observed metadata for one direct requirement, without importing it."""

    requirement: str
    name: str
    installed_version: str | None
    status: str

    def to_mapping(self) -> dict[str, Any]:
        """Encode one dependency observation."""
        return dict(self.__dict__)


@dataclass(frozen=True)
class DependencyAudit:
    """Direct dependency audit; this is not an installation lock."""

    dependencies: tuple[DependencyStatus, ...]

    @property
    def satisfied(self) -> bool:
        """Whether every applicable direct requirement is installed."""
        return all(
            row.status in {"satisfied", "skipped"} for row in self.dependencies
        )

    def to_mapping(self) -> list[dict[str, Any]]:
        """Encode the snapshot, never a duplicate dependency declaration."""
        return [row.to_mapping() for row in self.dependencies]

    def require_satisfied(self) -> None:
        """Refuse startup when metadata is missing or incompatible."""
        if not self.satisfied:
            raise ProtocolValidationError(
                "Shared dependencies are missing or incompatible",
                reason_code="DEPENDENCY_UNSATISFIED",
            )


def _dependency_status(
    value: str,
    installed: str | None,
    environment: Mapping[str, str],
) -> DependencyStatus:
    requirement = _requirement(value)
    name = str(canonicalize_name(requirement.name))
    if requirement.marker and not requirement.marker.evaluate(
        environment=dict(environment),
    ):
        return DependencyStatus(value, name, None, "skipped")
    if installed is None:
        return DependencyStatus(value, name, None, "missing")
    try:
        version = Version(installed)
        compatible = requirement.specifier.contains(version, prereleases=True)
    except InvalidVersion:
        compatible = False
    return DependencyStatus(
        value,
        name,
        installed,
        "satisfied" if compatible else "incompatible",
    )


def audit_shared_dependencies(
    requirements_path: str | Path,
    *,
    versions: Mapping[str, str] | None = None,
) -> DependencyAudit:
    """Read requirements and installed metadata; never import SDK modules."""
    environment = default_environment()
    supplied = (
        None
        if versions is None
        else {
            str(canonicalize_name(key)): value
            for key, value in versions.items()
        }
    )
    rows = []
    for value in _read_requirements(requirements_path):
        requirement = _requirement(value)
        name = str(canonicalize_name(requirement.name))
        installed = None
        if not requirement.marker or requirement.marker.evaluate(
            environment=environment,
        ):
            if supplied is not None:
                installed = supplied.get(name)
            else:
                try:
                    installed = metadata.version(name)
                except metadata.PackageNotFoundError:
                    pass
        rows.append(_dependency_status(value, installed, environment))
    return DependencyAudit(tuple(rows))


def _marker_environment(value: object) -> dict[str, str]:
    data = _protocol_object(value, frozenset(default_environment()))
    if any(not isinstance(item, str) for item in data.values()):
        raise ProtocolValidationError(
            "marker_environment values must be strings",
        )
    return dict(data)


def _dependency_snapshot(
    value: object,
    environment: Mapping[str, str],
) -> DependencyAudit:
    if not isinstance(value, list):
        raise ProtocolValidationError("dependencies must be an array")
    rows = []
    for raw in value:
        data = _protocol_object(raw, _DEPENDENCY_FIELDS)
        requirement = canonicalize_requirements(
            [_string(data["requirement"], "requirement")],
        )[0]
        installed = data["installed_version"]
        if installed is not None and not isinstance(installed, str):
            raise ProtocolValidationError(
                "installed_version must be a string or null",
            )
        row = _dependency_status(requirement, installed, environment)
        DependencyAudit((row,)).require_satisfied()
        if row.to_mapping() != {**data, "requirement": requirement}:
            raise ProtocolValidationError(
                "Dependency snapshot conflicts with version or marker",
                reason_code="DEPENDENCY_UNSATISFIED",
            )
        rows.append(row)
    requirements = [row.requirement for row in rows]
    if tuple(requirements) != canonicalize_requirements(requirements):
        raise ProtocolValidationError(
            "Dependency requirements must be canonical, sorted and unique",
        )
    audit = DependencyAudit(tuple(rows))
    audit.require_satisfied()
    return audit


@dataclass(frozen=True)
class SharedHelloParams(IdentityParams):
    """Shared environment identity without fabricated lock/environment IDs."""

    protocol_version: int
    dependency_mode: str
    qwenpaw_version: str
    source_revision: str
    python_abi: str
    platform_tag: str
    dependencies: tuple[DependencyStatus, ...]
    marker_environment: Mapping[str, str]
    capabilities: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: object) -> SharedHelloParams:
        """Validate shared identity and observed dependency versions."""
        data = _protocol_object(value, _HELLO_FIELDS)
        if (
            type(data["protocol_version"]) is not int
            or data["protocol_version"] != SHARED_PROTOCOL_VERSION
        ):
            raise ProtocolValidationError(
                "Unsupported shared protocol",
                reason_code="PROTOCOL_MISMATCH",
            )
        if data["dependency_mode"] != "shared":
            raise ProtocolValidationError("dependency_mode must be shared")
        environment = _marker_environment(data["marker_environment"])
        try:
            identity = _identity_from_fields(data)
            source_revision = validate_digest(data["source_revision"])
            python_abi = validate_python_abi(data["python_abi"])
            platform_tag = validate_platform_tag(
                data["platform_tag"],
                allowed_platform_tags=(data["platform_tag"],),
            )
            audit = _dependency_snapshot(data["dependencies"], environment)
        except DescriptorValidationError as exc:
            raise ProtocolValidationError(str(exc)) from exc
        return cls(
            **identity.to_mapping(),
            protocol_version=SHARED_PROTOCOL_VERSION,
            dependency_mode="shared",
            qwenpaw_version=_string(
                data["qwenpaw_version"],
                "qwenpaw_version",
            ),
            source_revision=source_revision,
            python_abi=python_abi,
            platform_tag=platform_tag,
            dependencies=audit.dependencies,
            marker_environment=environment,
            capabilities=_capabilities(data["capabilities"]),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Encode only shared environment identity fields."""
        return {
            **super().to_mapping(),
            "protocol_version": self.protocol_version,
            "dependency_mode": self.dependency_mode,
            "qwenpaw_version": self.qwenpaw_version,
            "source_revision": self.source_revision,
            "python_abi": self.python_abi,
            "platform_tag": self.platform_tag,
            "dependencies": [row.to_mapping() for row in self.dependencies],
            "marker_environment": dict(self.marker_environment),
            "capabilities": list(self.capabilities),
        }


def validate_channel_contract(channel_key: str, capabilities) -> None:
    """Reject unimplemented contracts before candidate activation."""
    from .models import (
        CONTENT_SOURCE_CAPABILITY,
        SEMANTIC_PARTS_CAPABILITY,
        RAW_COMPLETED_TEXT_CAPABILITY,
        UNKNOWN_ACTOR_CAPABILITY,
        APPROVAL_RESOLUTION_CAPABILITY,
        TEXT_MERGE_CAPABILITY,
        AUTH_QRCODE_CAPABILITY,
    )

    tags = set(capabilities)
    for supported in (
        CONTENT_SOURCE_CAPABILITY,
        SEMANTIC_PARTS_CAPABILITY,
        RAW_COMPLETED_TEXT_CAPABILITY,
        UNKNOWN_ACTOR_CAPABILITY,
        APPROVAL_RESOLUTION_CAPABILITY,
        TEXT_MERGE_CAPABILITY,
        AUTH_QRCODE_CAPABILITY,
    ):
        prefix = supported.rsplit(".", 1)[0] + "."
        claimed = {item for item in tags if item.startswith(prefix)}
        if claimed and (
            claimed != {supported} or "channel.generic.v1" not in tags
        ):
            raise ProtocolValidationError(
                "Unsupported send capability contract",
                reason_code="CHANNEL_CONTRACT_UNSUPPORTED",
            )
    contracts = {
        item for item in capabilities if item.startswith("channel.generic.")
    }
    if contracts and contracts != {"channel.generic.v1"}:
        raise ProtocolValidationError(
            "Unsupported channel contract",
            reason_code="CHANNEL_CONTRACT_UNSUPPORTED",
        )
    if not contracts:
        raise ProtocolValidationError(
            "Channel contract required",
            reason_code="CHANNEL_CONTRACT_UNSUPPORTED",
        )


def validate_shared_hello(
    hello: SharedHelloParams | Mapping[str, Any],
    *,
    channel_key: str,
    instance_id: str,
    generation: int,
    source_revision: str,
    qwenpaw_version: str,
    python_abi: str | None = None,
    platform_tag: str | None = None,
    expected_requirements: tuple[str, ...],
    capabilities: tuple[str, ...] | None = None,
) -> SharedHelloParams:
    """Check child observations against the parent's authoritative launch."""
    parsed = SharedHelloParams.from_mapping(
        hello.to_mapping() if isinstance(hello, SharedHelloParams) else hello,
    )
    for field, expected, reason in (
        ("channel_key", channel_key, "CHANNEL_KEY_MISMATCH"),
        ("instance_id", instance_id, "INSTANCE_ID_MISMATCH"),
        ("generation", generation, "GENERATION_MISMATCH"),
        ("source_revision", source_revision, "SOURCE_REVISION_MISMATCH"),
        ("qwenpaw_version", qwenpaw_version, "QWENPAW_VERSION_MISMATCH"),
        ("python_abi", python_abi, "PYTHON_ABI_MISMATCH"),
        ("platform_tag", platform_tag, "PLATFORM_TAG_MISMATCH"),
    ):
        if expected is not None and getattr(parsed, field) != expected:
            raise ProtocolValidationError(
                f"Shared hello {field} mismatch",
                reason_code=reason,
            )
    if (
        tuple(row.requirement for row in parsed.dependencies)
        != expected_requirements
    ):
        raise ProtocolValidationError(
            "Shared dependency declaration mismatch",
            reason_code="DEPENDENCY_UNSATISFIED",
        )
    if capabilities is not None:
        validate_channel_contract(channel_key, capabilities)
        if set(parsed.capabilities) != set(capabilities):
            raise ProtocolValidationError(
                "Shared capabilities mismatch",
                reason_code="CAPABILITY_MISMATCH",
            )
    return parsed

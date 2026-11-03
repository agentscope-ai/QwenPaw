# -*- coding: utf-8 -*-
"""Plugin architecture definitions."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .dependency_requirements import (
    resolve_optional_dependencies,
    validate_optional_dependencies,
)

if TYPE_CHECKING:
    from .execution_backend import BackendBinding


class PluginType(str, Enum):
    """Canonical plugin type identifiers.

    Values are lowercase strings so they serialise cleanly in JSON API
    responses without extra ``.value`` calls.
    """

    TOOL = "tool"
    """Registers one or more agent tools (functions the LLM can call)."""

    PROVIDER = "provider"
    """Registers a custom LLM provider / model endpoint."""

    HOOK = "hook"
    """Runs code during application startup or shutdown."""

    COMMAND = "command"
    """Registers one or more /slash control commands."""

    CHANNEL = "channel"
    """Registers a custom messaging channel."""

    HUB = "hub"
    """Registers a Skill marketplace source."""

    MEMORY = "memory"
    """Registers a memory backend required before workspace startup."""

    FRONTEND = "frontend"
    """Ships a frontend JS bundle loaded dynamically by the UI."""

    APP = "app"
    """A PawApp: a full app (backend router + UI page) authored with the
    PawApp SDK and described by a ``manifest.yaml``. Loaded through the
    same pipeline as other plugins; surfaced only in the App Center."""

    GENERAL = "general"
    """Fallback for plugins that do not match any specific category."""


class PluginEntryPoints(BaseModel):
    """Plugin entry points for frontend and backend."""

    model_config = ConfigDict(extra="ignore")

    frontend: Optional[str] = None
    backend: Optional[str] = None
    descriptor: Optional[str] = None

    @model_validator(mode="after")
    def _validate_descriptor(self):
        if self.descriptor is None:
            return self
        path = str(self.descriptor)
        if (
            path != path.strip()
            or "\\" in path
            or ":" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or not path.endswith(".json")
        ):
            raise ValueError(
                "descriptor must be a canonical relative JSON path",
            )
        return self


def _coerce_manifest_str(value: Any) -> str:
    """Return a display string from manifest text or legacy i18n object.

    Manifests may carry ``name`` / ``description`` either as plain
    strings or as ``{"zh-CN": ..., "en-US": ...}`` mappings.  This
    helper picks the first non-empty localised value with English first.
    """
    if isinstance(value, dict):
        return str(
            value.get("en-US")
            or value.get("en")
            or value.get("zh-CN")
            or value.get("zh")
            or "",
        )
    return str(value) if value is not None else ""


def _infer_type_from_meta(  # pylint: disable=too-many-return-statements
    meta: Dict[str, Any],
    entry: PluginEntryPoints,
) -> PluginType:
    """Infer the primary type from meta fields (legacy fallback).

    Used when ``plugin.json`` does not set the explicit ``type`` field,
    which is the case for older manifests written before the field
    existed.

    Args:
        meta: Parsed ``meta`` section of the manifest.
        entry: Parsed entry points.

    Returns:
        Best-guess :class:`PluginType`.
    """
    if meta.get("tools") or meta.get("tool_name"):
        return PluginType.TOOL
    if meta.get("chat_model") or meta.get("provider_id"):
        return PluginType.PROVIDER
    if meta.get("hook_type"):
        return PluginType.HOOK
    if meta.get("command_name") or meta.get("commands"):
        return PluginType.COMMAND
    if meta.get("channel"):
        return PluginType.CHANNEL
    if entry.frontend:
        return PluginType.FRONTEND
    return PluginType.GENERAL


class QwenPawVersionConstraint(BaseModel):
    """QwenPaw version compatibility range (left-closed, right-open).

    Semantics: ``>=min, <max``.  When ``max`` is omitted the allowed
    range is all patch versions of the same minor (derived as
    ``{major}.{minor+1}.0`` from ``min``).
    """

    model_config = ConfigDict(extra="ignore")

    min: str
    max: Optional[str] = None


class CliDeclaration(BaseModel):
    """Static mount metadata; Click owns parameters and command behavior."""

    id: str = Field(min_length=1)
    path: tuple[str, ...] = Field(min_length=1)
    kind: Literal["command", "group"] = "command"
    help: str = ""
    requires: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_path(self):
        if any(
            not part
            or part.startswith("-")
            or part in {".", ".."}
            or any(c.isspace() or c in "/\\" for c in part)
            for part in self.path
        ):
            raise ValueError("cli.path must contain command names")
        return self


class ExtensionDeclaration(BaseModel):
    """A named contribution to a host contract with optional requirements."""

    point: str = Field(min_length=1)
    id: str = Field(min_length=1)
    requires: tuple[str, ...] = ()


class PluginManifest(BaseModel):
    """Plugin manifest definition.

    Validated against ``plugin.json``.  Unknown top-level fields are
    ignored so manifests can carry display-only data (e.g.
    ``description_i18n``) or packaging-only flags (e.g. ``publish``)
    without tripping validation.

    The ``plugin_type`` field should be set explicitly via the ``type``
    key in ``plugin.json``.  Manifests that omit it fall back to a
    best-effort inference from ``meta`` so old plugins keep loading.
    """

    model_config = ConfigDict(
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    name: str = ""
    description: str = ""
    # Per-locale descriptions (e.g. {"zh-CN": ..., "en-US": ...}) surfaced
    # to UI listings such as the App Center; not used for loading logic.
    description_i18n: Dict[str, str] = Field(default_factory=dict)
    author: str = ""
    entry: PluginEntryPoints = Field(default_factory=PluginEntryPoints)
    cli: tuple[CliDeclaration, ...] = ()
    extensions: tuple[ExtensionDeclaration, ...] = ()
    dependencies: List[str] = Field(default_factory=list)
    optional_dependencies: Dict[str, List[str]] = Field(default_factory=dict)
    min_version: str = "0.1.0"
    max_version: Optional[str] = None
    qwenpaw_version: Optional[QwenPawVersionConstraint] = None
    sdk: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    plugin_type: PluginType = PluginType.GENERAL

    def declares_extension(self, point: str) -> bool:
        """Select a host contract without importing contribution code."""
        return any(item.point == point for item in self.extensions)

    @model_validator(mode="after")
    def _validate_optional_dependencies(self):
        validate_optional_dependencies(self.optional_dependencies)
        for declaration in (*self.cli, *self.extensions):
            resolve_optional_dependencies(
                self.optional_dependencies,
                declaration.requires,
            )
        capabilities = (self.sdk or {}).get("capabilities", ())
        if self.optional_dependencies and (
            not isinstance(capabilities, (list, tuple))
            or "dependencies" not in capabilities
        ):
            raise ValueError(
                "optional_dependencies require the dependencies SDK capability",
            )
        return self

    @model_validator(mode="after")
    def _validate_cli_contract(self):
        # Pydantic resolves nested entry models before after-validators.
        # pylint: disable=no-member
        if not self.cli:
            return self
        caps = (self.sdk or {}).get("capabilities", ())
        if not isinstance(caps, (list, tuple)) or not all(
            isinstance(cap, str) for cap in caps
        ):
            raise ValueError("sdk.capabilities must be a list of names")
        if "cli" not in caps or not self.entry.backend:
            raise ValueError(
                "cli declarations require cli capability and entry.backend",
            )
        if len({c.id for c in self.cli}) != len(self.cli):
            raise ValueError("cli IDs must be unique within a plugin")
        if len({c.path for c in self.cli}) != len(self.cli):
            raise ValueError("cli paths must be unique within a plugin")
        return self

    @model_validator(mode="after")
    def _validate_extensions(self):
        if not self.extensions:
            return self
        caps = (self.sdk or {}).get("capabilities", ())
        if not isinstance(caps, (list, tuple)) or not all(
            isinstance(cap, str) for cap in caps
        ):
            raise ValueError("sdk.capabilities must be a list of names")
        if "extensions" not in caps or not self.entry.backend:
            raise ValueError(
                "extensions require extensions capability and entry.backend",
            )
        keys = [(item.point, item.id) for item in self.extensions]
        if len(set(keys)) != len(keys):
            raise ValueError("Extension contribution IDs must be unique")
        return self

    @model_validator(mode="before")
    @classmethod
    def _normalise_input(cls, data: Any) -> Any:
        """Normalise raw ``plugin.json`` input before field validation.

        Handles three legacy shapes that real manifests still use:
          * ``name`` / ``description`` / ``author`` given as
            ``{"zh-CN": ..., "en-US": ...}`` mappings.
          * Top-level ``entry_point`` instead of ``entry.backend``.
          * Missing or invalid ``type`` — inferred from ``meta``.
        """
        if not isinstance(data, dict):
            return data

        # Work on a shallow copy so callers' dicts aren't mutated.
        data = dict(data)

        # Localised text → display string.
        for key in ("name", "description", "author"):
            if key in data:
                data[key] = _coerce_manifest_str(data[key])

        # ``description_i18n`` must be a str→str mapping; anything else is
        # dropped so malformed manifests keep loading.
        raw_i18n = data.get("description_i18n")
        if isinstance(raw_i18n, dict):
            data["description_i18n"] = {
                str(k): v for k, v in raw_i18n.items() if isinstance(v, str)
            }
        else:
            data.pop("description_i18n", None)

        # ``name`` defaults to ``id`` when missing or empty.
        if not data.get("name"):
            data["name"] = data.get("id", "")

        # ``entry`` may be absent; merge legacy ``entry_point`` into it.
        entry_data = data.get("entry") or {}
        if not isinstance(entry_data, dict):
            entry_data = {}
        legacy_entry_point = data.get("entry_point")
        if legacy_entry_point and not entry_data.get("backend"):
            entry_data["backend"] = legacy_entry_point
        data["entry"] = entry_data

        if entry_data.get("descriptor") is not None:
            try:
                PluginType(data.get("type"))
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "descriptor entry requires an explicit valid plugin type",
                ) from exc

        # Resolve ``type``: explicit value wins; otherwise infer.  We
        # need the parsed entry/meta to infer, so do a light parse here.
        raw_type = data.get("type")
        try:
            data["plugin_type"] = PluginType(raw_type)
        except (ValueError, TypeError):
            tmp_entry = PluginEntryPoints(**entry_data)
            tmp_meta = data.get("meta") or {}
            data["plugin_type"] = _infer_type_from_meta(tmp_meta, tmp_entry)

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        """Create a manifest from a ``plugin.json`` dictionary.

        Thin wrapper around :meth:`model_validate` kept for backwards
        compatibility with existing callers (loader, routers, tests).

        Args:
            data: Parsed ``plugin.json`` content.

        Returns:
            :class:`PluginManifest` instance.

        Raises:
            pydantic.ValidationError: If required fields are missing
                or have the wrong type.
        """
        return cls.model_validate(data)


@dataclass
class PluginRecord:
    """Loaded source and execution state.

    ``enabled`` is effective execution eligibility. ``global_enabled`` keeps
    the user's enable intent when a backend temporarily blocks execution;
    None preserves the effective flag for legacy manually constructed rows.
    """

    manifest: PluginManifest
    source_path: Path
    enabled: bool
    instance: Optional[Any] = None
    diagnostics: List[str] = field(default_factory=list)
    status: str = "active"
    backend_binding: Optional["BackendBinding"] = field(
        default=None,
        repr=False,
    )
    global_enabled: Optional[bool] = None

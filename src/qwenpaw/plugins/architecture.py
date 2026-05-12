# -*- coding: utf-8 -*-
"""Plugin architecture definitions."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from pathlib import Path


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

    FRONTEND = "frontend"
    """Ships a frontend JS bundle loaded dynamically by the UI."""

    GENERAL = "general"
    """Fallback for plugins that do not match any specific category."""


@dataclass
class PluginEntryPoints:
    """Plugin entry points for frontend and backend."""

    frontend: Optional[str] = None
    backend: Optional[str] = None


@dataclass
class PluginManifest:
    """Plugin manifest definition.

    The ``plugin_type`` field should be set explicitly via the
    ``"type"`` key in ``plugin.json``.  For legacy manifests that omit
    it, :meth:`from_dict` falls back to a best-effort inference from
    ``meta`` so old plugins continue to work without modification.
    """

    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    entry: PluginEntryPoints = field(default_factory=PluginEntryPoints)
    dependencies: List[str] = field(default_factory=list)
    min_version: str = "0.1.0"
    meta: Dict[str, Any] = field(default_factory=dict)
    plugin_type: PluginType = PluginType.GENERAL

    @classmethod
    def _type_from_meta(
        cls,
        meta: Dict[str, Any],
        entry: PluginEntryPoints,
    ) -> PluginType:
        """Infer the primary type from meta fields (legacy fallback).

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
        if entry.frontend:
            return PluginType.FRONTEND
        return PluginType.GENERAL

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        """Create a manifest from a ``plugin.json`` dictionary.

        Args:
            data: Parsed ``plugin.json`` content.

        Returns:
            :class:`PluginManifest` instance.
        """
        entry_data = data.get("entry", {})
        legacy_entry_point = data.get("entry_point", "plugin.py")
        entry = PluginEntryPoints(
            frontend=entry_data.get("frontend"),
            backend=entry_data.get("backend") or legacy_entry_point,
        )
        meta = data.get("meta", {})

        # Prefer the explicit "type" field; fall back to inference so
        # that manifests written before this field was introduced keep
        # working without any changes.
        raw_type = data.get("type", "")
        try:
            plugin_type = PluginType(raw_type)
        except ValueError:
            plugin_type = cls._type_from_meta(meta, entry)

        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry=entry,
            dependencies=data.get("dependencies", []),
            min_version=data.get("min_version", "0.1.0"),
            meta=meta,
            plugin_type=plugin_type,
        )


@dataclass
class PluginRecord:
    """Plugin record for loaded plugins."""

    manifest: PluginManifest
    source_path: Path
    enabled: bool
    instance: Optional[Any] = None
    diagnostics: List[str] = field(default_factory=list)

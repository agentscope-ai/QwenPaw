# -*- coding: utf-8 -*-
"""Plugin architecture definitions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from pathlib import Path

if TYPE_CHECKING:
    from .api import PluginApi


class BasePlugin(ABC):
    """Abstract base class for all plugins.

    Every plugin must export a ``plugin`` object that is an instance of a
    class derived from ``BasePlugin``.  The loader calls ``register`` on
    startup.

    Example::

        class MyPlugin(BasePlugin):
            def register(self, api: PluginApi) -> None:
                api.register_provider(...)

        plugin = MyPlugin()
    """

    @abstractmethod
    def register(self, api: "PluginApi") -> None:
        """Called when the plugin is loaded.

        Use the *api* object to register providers, hooks, and other
        capabilities.

        Args:
            api: The plugin API instance bound to this plugin.
        """


@dataclass
class PluginEntryPoints:
    """Plugin entry points for frontend and backend."""

    frontend: Optional[str] = None
    backend: Optional[str] = None


@dataclass
class PluginManifest:
    """Plugin manifest definition."""

    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    entry: PluginEntryPoints = field(default_factory=PluginEntryPoints)
    dependencies: List[str] = field(default_factory=list)
    min_version: str = "0.1.0"
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        """Create manifest from dictionary.

        Args:
            data: Manifest data dictionary

        Returns:
            PluginManifest instance
        """
        entry_data = data.get("entry", {})
        entry = PluginEntryPoints(
            frontend=entry_data.get("frontend"),
            backend=entry_data.get("backend", "plugin.py"),
        )

        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry=entry,
            dependencies=data.get("dependencies", []),
            min_version=data.get("min_version", "0.1.0"),
            meta=data.get("meta", {}),
        )


@dataclass
class PluginRecord:
    """Plugin record for loaded plugins."""

    manifest: PluginManifest
    source_path: Path
    enabled: bool
    instance: Optional[Any] = None
    api: Optional["PluginApi"] = None
    diagnostics: List[str] = field(default_factory=list)

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
    startup and ``unregister`` before the plugin is unloaded, giving the
    plugin a chance to clean up resources it registered.

    Example::

        class MyPlugin(BasePlugin):
            def register(self, api: PluginApi) -> None:
                api.register_js_tool_renderer("view_image", "ViewImageCard")

            def unregister(self, api: PluginApi) -> None:
                # Optional: custom cleanup beyond automatic unregister_all()
                pass

        plugin = MyPlugin()
    """

    @abstractmethod
    def register(self, api: "PluginApi") -> None:
        """Called when the plugin is loaded.

        Use the *api* object to register providers, hooks, JS tool
        renderers, and other capabilities.

        Args:
            api: The plugin API instance bound to this plugin.
        """

    def unregister(self, api: "PluginApi") -> None:
        """Called when the plugin is about to be unloaded.

        Override this to perform custom cleanup.  The framework will
        **always** call ``api.unregister_all()`` after this method returns,
        so you only need to override it if you have resources outside the
        plugin registry to release (e.g. background tasks, open files).

        Args:
            api: The plugin API instance bound to this plugin.
        """


@dataclass
class PluginManifest:
    """Plugin manifest definition."""

    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    entry_point: str = "plugin.py"
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
        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry_point=data.get("entry_point", "plugin.py"),
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
